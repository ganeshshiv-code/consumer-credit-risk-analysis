-- ============================================================================
-- 01_portfolio_overview.sql
-- Purpose: establish the baseline. How big is the book, how seasoned is it,
--          and how much of it is already showing stress?
-- Engine:  DuckDB (ANSI-standard SQL; window functions, CTEs, FILTER)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Q1. Portfolio at a glance
-- ----------------------------------------------------------------------------
WITH base AS (
    SELECT
        COUNT(*)                                     AS loans,
        SUM(loan_amount)                             AS originated,
        SUM(balance)                                 AS outstanding,
        SUM(balance) / SUM(loan_amount)              AS pct_outstanding,
        AVG(loan_amount)                             AS avg_loan,
        SUM(balance * interest_rate)
            / SUM(balance)                           AS wavg_coupon,
        AVG(payments_made)                           AS avg_payments_made,
        SUM(is_impaired)                             AS impaired_loans,
        AVG(is_impaired)                             AS impaired_rate,
        SUM(balance) FILTER (WHERE is_impaired = 1)  AS impaired_balance
    FROM loans
)
SELECT
    loans,
    ROUND(originated / 1e6, 1)                       AS originated_musd,
    ROUND(outstanding / 1e6, 1)                      AS outstanding_musd,
    ROUND(avg_loan, 0)                               AS avg_loan_usd,
    ROUND(wavg_coupon, 2)                            AS wavg_coupon_pct,
    ROUND(avg_payments_made, 1)                      AS avg_payments_made,
    impaired_loans,
    ROUND(100 * impaired_rate, 2)                    AS impaired_rate_pct,
    ROUND(impaired_balance / 1e6, 2)                 AS impaired_balance_musd,
    ROUND(100 * impaired_balance / outstanding, 2)   AS impaired_balance_pct
FROM base;


-- ----------------------------------------------------------------------------
-- Q2. Delinquency waterfall — where in the cycle is the stress sitting?
--     A book this young should have almost nothing beyond Grace Period.
-- ----------------------------------------------------------------------------
SELECT
    loan_status,
    COUNT(*)                                                       AS loans,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)             AS pct_of_loans,
    ROUND(SUM(balance) / 1e6, 2)                                   AS balance_musd,
    ROUND(100.0 * SUM(balance) / SUM(SUM(balance)) OVER (), 2)     AS pct_of_balance,
    ROUND(AVG(interest_rate), 2)                                   AS avg_coupon_pct,
    -- probability this bucket eventually charges off (business assumption)
    ROUND(AVG(roll_to_co), 2)                                      AS roll_to_charge_off,
    ROUND(SUM(ew_loss_usd) / 1e3, 0)                               AS ew_loss_kusd
FROM loans
GROUP BY loan_status
ORDER BY roll_to_charge_off DESC, loans DESC;


-- ----------------------------------------------------------------------------
-- Q3. Vintage check — are the three monthly cohorts comparable?
--     If March looks worse than January it is a seasoning artefact, not a
--     credit signal, because January has had one more payment to miss.
-- ----------------------------------------------------------------------------
SELECT
    issue_date,
    COUNT(*)                                            AS loans,
    ROUND(AVG(payments_made), 2)                        AS avg_payments_made,
    ROUND(100 * AVG(is_impaired), 2)                    AS impaired_rate_pct,
    -- normalise: impairment per payment opportunity
    ROUND(100 * AVG(is_impaired) / AVG(payments_made), 3) AS impaired_per_payment,
    ROUND(AVG(interest_rate), 2)                        AS avg_coupon_pct,
    ROUND(SUM(loan_amount) / 1e6, 1)                    AS originated_musd
FROM loans
GROUP BY issue_date
ORDER BY issue_date;


-- ----------------------------------------------------------------------------
-- Q4. Does the credit grade actually work?
--     Before hunting for new risk drivers, confirm the existing one is sound.
--     A working grade shows monotonically rising impairment AND a coupon that
--     rises at least as fast.
-- ----------------------------------------------------------------------------
WITH by_grade AS (
    SELECT
        grade,
        COUNT(*)                            AS loans,
        SUM(is_impaired)                    AS impaired,
        AVG(is_impaired)                    AS impaired_rate,
        AVG(interest_rate)                  AS avg_coupon,
        SUM(balance)                        AS balance
    FROM loans
    GROUP BY grade
)
SELECT
    grade,
    loans,
    impaired,
    ROUND(100 * impaired_rate, 2)                                   AS impaired_rate_pct,
    ROUND(avg_coupon, 2)                                            AS avg_coupon_pct,
    -- incremental risk vs incremental price, grade over grade
    ROUND(100 * (impaired_rate - LAG(impaired_rate) OVER (ORDER BY grade)), 2)
                                                                    AS delta_risk_pp,
    ROUND(avg_coupon - LAG(avg_coupon) OVER (ORDER BY grade), 2)     AS delta_price_pp,
    -- how many points of coupon are charged per point of extra impairment
    ROUND(
        (avg_coupon - LAG(avg_coupon) OVER (ORDER BY grade))
        / NULLIF(100 * (impaired_rate - LAG(impaired_rate) OVER (ORDER BY grade)), 0)
    , 1)                                                            AS price_per_risk_point,
    ROUND(balance / 1e6, 1)                                         AS balance_musd
FROM by_grade
ORDER BY grade;
