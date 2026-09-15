-- ============================================================================
-- 03_segment_economics.sql
-- Purpose: turn impairment rates into money. A segment is only a problem if it
--          fails to earn its cost of funds, servicing and expected loss.
--
--          net yield = coupon - funding - servicing - annualised expected loss
--
-- Engine:  DuckDB
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Q1. The economic ladder by grade.
--     Read the net_yield column, not the impairment column: grade E impairs
--     6.5x more than grade A and is still the more profitable asset.
-- ----------------------------------------------------------------------------
WITH port AS (
    SELECT 100 * SUM(net_margin_usd) / SUM(balance) AS p_net FROM loans
)
SELECT
    l.grade,
    COUNT(*)                                                AS loans,
    ROUND(SUM(l.balance) / 1e6, 1)                          AS balance_musd,
    ROUND(100.0 * AVG(l.is_impaired), 2)                    AS impaired_rate_pct,
    ROUND(100 * SUM(l.revenue_usd)     / SUM(l.balance), 2) AS coupon_pct,
    ROUND(100 * SUM(l.annual_loss_usd) / SUM(l.balance), 2) AS annual_loss_pct,
    ROUND(100 * SUM(l.net_margin_usd)  / SUM(l.balance), 2) AS net_yield_pct,
    ROUND(100 * (100 * SUM(l.net_margin_usd) / SUM(l.balance) - MIN(p.p_net)), 0)
                                                            AS vs_portfolio_bps
FROM loans l CROSS JOIN port p
GROUP BY l.grade
ORDER BY l.grade;


-- ----------------------------------------------------------------------------
-- Q2. The segment league table — every cut that the hypothesis tests flagged,
--     ranked by how far its net yield sits from the portfolio.
--     This is the single table the credit committee needs.
-- ----------------------------------------------------------------------------
WITH labelled AS (
    SELECT 'PORTFOLIO'                    AS segment, 0 AS sort_key, * FROM loans
    UNION ALL
    SELECT 'Grade A - income Verified',   1, * FROM loans
        WHERE grade = 'A' AND income_verified_flag = 1
    UNION ALL
    SELECT 'Grade A - not/source verified', 2, * FROM loans
        WHERE grade = 'A' AND income_verified_flag = 0
    UNION ALL
    SELECT 'Grade B - income Verified',   3, * FROM loans
        WHERE grade = 'B' AND income_verified_flag = 1
    UNION ALL
    SELECT 'Purpose: house',              4, * FROM loans
        WHERE loan_purpose = 'house'
    UNION ALL
    SELECT 'Purpose: elevated set',       5, * FROM loans
        WHERE elevated_purpose_flag = 1
    UNION ALL
    SELECT 'Purpose: credit_card',        6, * FROM loans
        WHERE loan_purpose = 'credit_card'
    UNION ALL
    SELECT 'Purpose: debt_consolidation', 7, * FROM loans
        WHERE loan_purpose = 'debt_consolidation'
    UNION ALL
    SELECT 'Homeowner: OWN outright',     8, * FROM loans
        WHERE homeownership = 'OWN'
    UNION ALL
    SELECT 'Homeowner: MORTGAGE',         9, * FROM loans
        WHERE homeownership = 'MORTGAGE'
    UNION ALL
    SELECT 'Joint application',          10, * FROM loans
        WHERE application_type = 'joint'
),
agg AS (
    SELECT
        segment, sort_key,
        COUNT(*)                                          AS loans,
        SUM(balance)                                      AS balance,
        AVG(is_impaired)                                  AS impaired_rate,
        100 * SUM(revenue_usd)     / SUM(balance)         AS coupon_pct,
        100 * SUM(annual_loss_usd) / SUM(balance)         AS annual_loss_pct,
        100 * SUM(net_margin_usd)  / SUM(balance)         AS net_yield_pct
    FROM labelled
    GROUP BY segment, sort_key
)
SELECT
    segment,
    loans,
    ROUND(balance / 1e6, 2)                                       AS balance_musd,
    ROUND(100 * impaired_rate, 2)                                 AS impaired_rate_pct,
    ROUND(coupon_pct, 2)                                          AS coupon_pct,
    ROUND(annual_loss_pct, 2)                                     AS annual_loss_pct,
    ROUND(net_yield_pct, 2)                                       AS net_yield_pct,
    ROUND(100 * (net_yield_pct
        - MAX(CASE WHEN segment = 'PORTFOLIO' THEN net_yield_pct END) OVER ()), 0)
                                                                  AS vs_portfolio_bps,
    CASE
        WHEN net_yield_pct < 0 THEN 'VALUE DESTROYING'
        WHEN net_yield_pct <
             MAX(CASE WHEN segment = 'PORTFOLIO' THEN net_yield_pct END) OVER ()
             THEN 'BELOW PORTFOLIO'
        ELSE 'ACCRETIVE'
    END                                                           AS verdict
FROM agg
ORDER BY sort_key;


-- ----------------------------------------------------------------------------
-- Q3. Risk concentration by uncompensated-risk flag count.
--
--     Deciling loan-level expected loss is useless on a 4-month book: loss is
--     zero for every loan that has not yet missed a payment, so decile 1 takes
--     100% of it by construction. The question that can be answered is whether
--     the flags raised in 02_hypothesis_tests.sql CONCENTRATE loss — i.e. does
--     a flagged minority of the book carry a majority share of the damage.
-- ----------------------------------------------------------------------------
WITH flagged AS (
    SELECT
        (CASE WHEN is_prime = 1 AND income_verified_flag = 1 THEN 1 ELSE 0 END)
      + (CASE WHEN elevated_purpose_flag = 1                 THEN 1 ELSE 0 END)
      + (CASE WHEN outright_owner_flag = 1                   THEN 1 ELSE 0 END)  AS flag_count,
        balance, is_impaired, interest_rate, annual_loss_usd
    FROM loans
),
binned AS (
    SELECT
        CASE WHEN flag_count >= 2 THEN '2+ flags'
             WHEN flag_count = 1  THEN '1 flag'
             ELSE '0 flags' END                                     AS risk_flags,
        flag_count, balance, is_impaired, interest_rate, annual_loss_usd
    FROM flagged
)
SELECT
    risk_flags,
    COUNT(*)                                                        AS loans,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)              AS pct_of_loans,
    ROUND(100.0 * SUM(balance) / SUM(SUM(balance)) OVER (), 1)      AS pct_of_balance,
    ROUND(100.0 * AVG(is_impaired), 2)                              AS impaired_rate_pct,
    ROUND(AVG(interest_rate), 2)                                    AS avg_coupon_pct,
    ROUND(100.0 * SUM(annual_loss_usd)
          / SUM(SUM(annual_loss_usd)) OVER (), 1)                   AS pct_of_modelled_loss,
    -- >1.0 means the segment absorbs more loss than its size justifies
    ROUND(
        (SUM(annual_loss_usd) / SUM(SUM(annual_loss_usd)) OVER ())
        / (SUM(balance)       / SUM(SUM(balance))       OVER ())
    , 2)                                                            AS loss_concentration_index
FROM binned
GROUP BY risk_flags
ORDER BY risk_flags;
