-- ============================================================================
-- 02_hypothesis_tests.sql
-- Purpose: test the five hypotheses raised in the README, one query each.
--          Every result carries a Wilson 95% confidence interval, because on a
--          1.78% base rate a segment of 150 loans can swing wildly on noise.
-- Engine:  DuckDB
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Reusable macro: Wilson score interval for a binomial proportion.
-- Preferred over the normal approximation, which breaks down at low base rates
-- and small n — exactly the situation here.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE MACRO wilson_low(k, n) AS
    100 * (
        ((k::DOUBLE / n) + 1.96 * 1.96 / (2 * n)
         - 1.96 * sqrt((k::DOUBLE / n) * (1 - k::DOUBLE / n) / n
                       + 1.96 * 1.96 / (4 * n * n)))
        / (1 + 1.96 * 1.96 / n)
    );

CREATE OR REPLACE MACRO wilson_high(k, n) AS
    100 * (
        ((k::DOUBLE / n) + 1.96 * 1.96 / (2 * n)
         + 1.96 * sqrt((k::DOUBLE / n) * (1 - k::DOUBLE / n) / n
                       + 1.96 * 1.96 / (4 * n * n)))
        / (1 + 1.96 * 1.96 / n)
    );


-- ----------------------------------------------------------------------------
-- H1. "Income verification reduces risk."
--     Tested by credit band, because the verification decision is not random —
--     the platform chooses whom to verify.
-- ----------------------------------------------------------------------------
WITH banded AS (
    SELECT
        CASE WHEN is_prime = 1 THEN 'Prime (A-B)' ELSE 'Non-prime (C-G)' END AS band,
        CASE WHEN income_verified_flag = 1 THEN 'Verified'
             ELSE 'Not / source verified' END                                AS verification,
        is_impaired, interest_rate, balance
    FROM loans
)
SELECT
    band,
    verification,
    COUNT(*)                                            AS loans,
    SUM(is_impaired)                                    AS impaired,
    ROUND(100.0 * AVG(is_impaired), 2)                  AS impaired_rate_pct,
    ROUND(wilson_low(SUM(is_impaired), COUNT(*)), 2)    AS ci_low,
    ROUND(wilson_high(SUM(is_impaired), COUNT(*)), 2)   AS ci_high,
    ROUND(AVG(interest_rate), 2)                        AS avg_coupon_pct,
    -- risk multiple vs the other verification group in the same band
    ROUND(
        AVG(is_impaired) / MIN(AVG(is_impaired)) OVER (PARTITION BY band)
    , 2)                                                AS risk_multiple,
    ROUND(SUM(balance) / 1e6, 1)                        AS balance_musd
FROM banded
GROUP BY band, verification
ORDER BY band DESC, verification;


-- ----------------------------------------------------------------------------
-- H1b. Drill into grade A, where the effect is sharpest, and show that the
--      price does NOT move with the risk.
-- ----------------------------------------------------------------------------
SELECT
    grade,
    verified_income,
    COUNT(*)                                            AS loans,
    SUM(is_impaired)                                    AS impaired,
    ROUND(100.0 * AVG(is_impaired), 2)                  AS impaired_rate_pct,
    ROUND(wilson_low(SUM(is_impaired), COUNT(*)), 2)    AS ci_low,
    ROUND(wilson_high(SUM(is_impaired), COUNT(*)), 2)   AS ci_high,
    ROUND(AVG(interest_rate), 2)                        AS avg_coupon_pct,
    ROUND(SUM(balance) / 1e6, 2)                        AS balance_musd
FROM loans
WHERE grade IN ('A', 'B', 'C', 'D')
GROUP BY grade, verified_income
HAVING COUNT(*) >= 80
ORDER BY grade, verified_income;


-- ----------------------------------------------------------------------------
-- H2. "Loan purpose carries risk that the price does not reflect."
--     The test that matters is the gap between a purpose's risk RANK and its
--     price RANK. A purpose that is riskier than average but cheaper than
--     average is a leak.
-- ----------------------------------------------------------------------------
WITH by_purpose AS (
    SELECT
        loan_purpose,
        COUNT(*)                AS loans,
        SUM(is_impaired)        AS impaired,
        AVG(is_impaired)        AS impaired_rate,
        AVG(interest_rate)      AS avg_coupon,
        SUM(balance)            AS balance
    FROM loans
    GROUP BY loan_purpose
    HAVING COUNT(*) >= 100          -- suppress segments too small to read
),
port AS (
    SELECT AVG(is_impaired) AS p_rate,
           SUM(balance * interest_rate) / SUM(balance) AS p_coupon
    FROM loans
)
SELECT
    b.loan_purpose,
    b.loans,
    b.impaired,
    ROUND(100 * b.impaired_rate, 2)                         AS impaired_rate_pct,
    ROUND(wilson_low(b.impaired, b.loans), 2)               AS ci_low,
    ROUND(wilson_high(b.impaired, b.loans), 2)              AS ci_high,
    ROUND(b.impaired_rate / p.p_rate, 2)                    AS risk_vs_portfolio,
    ROUND(b.avg_coupon, 2)                                  AS avg_coupon_pct,
    ROUND(b.avg_coupon - p.p_coupon, 2)                     AS coupon_vs_portfolio_pp,
    -- the leak flag: more risk than the book, less price than the book
    CASE WHEN b.impaired_rate > p.p_rate AND b.avg_coupon < p.p_coupon
         THEN 'UNCOMPENSATED' ELSE '' END                   AS flag,
    ROUND(b.balance / 1e6, 2)                               AS balance_musd
FROM by_purpose b CROSS JOIN port p
ORDER BY b.impaired_rate DESC;


-- ----------------------------------------------------------------------------
-- H3. "Higher debt-to-income means higher risk."
--     Quintiles rather than a correlation, so a non-monotonic shape is visible.
-- ----------------------------------------------------------------------------
WITH q AS (
    SELECT
        NTILE(5) OVER (ORDER BY debt_to_income)  AS dti_quintile,
        debt_to_income, is_impaired, interest_rate
    FROM loans
    WHERE debt_to_income IS NOT NULL
)
SELECT
    dti_quintile,
    COUNT(*)                                            AS loans,
    ROUND(MIN(debt_to_income), 1)                       AS dti_min,
    ROUND(MAX(debt_to_income), 1)                       AS dti_max,
    SUM(is_impaired)                                    AS impaired,
    ROUND(100.0 * AVG(is_impaired), 2)                  AS impaired_rate_pct,
    ROUND(wilson_low(SUM(is_impaired), COUNT(*)), 2)    AS ci_low,
    ROUND(wilson_high(SUM(is_impaired), COUNT(*)), 2)   AS ci_high,
    ROUND(AVG(interest_rate), 2)                        AS avg_coupon_pct
FROM q
GROUP BY dti_quintile
ORDER BY dti_quintile;


-- ----------------------------------------------------------------------------
-- H4. "60-month loans are riskier than 36-month loans."
--     Must be tested WITHIN grade — long terms skew to weaker credits, so the
--     headline gap is mostly grade mix, not term.
-- ----------------------------------------------------------------------------
SELECT
    grade,
    term,
    COUNT(*)                                            AS loans,
    ROUND(100.0 * AVG(is_impaired), 2)                  AS impaired_rate_pct,
    ROUND(AVG(interest_rate), 2)                        AS avg_coupon_pct,
    ROUND(
        100 * AVG(is_impaired)
        - FIRST(100 * AVG(is_impaired)) OVER (PARTITION BY grade ORDER BY term)
    , 2)                                                AS impaired_gap_vs_36m_pp,
    ROUND(
        AVG(interest_rate)
        - FIRST(AVG(interest_rate)) OVER (PARTITION BY grade ORDER BY term)
    , 2)                                                AS coupon_gap_vs_36m_pp
FROM loans
WHERE grade IN ('A', 'B', 'C', 'D')
GROUP BY grade, term
ORDER BY grade, term;


-- ----------------------------------------------------------------------------
-- H5. "Housing status is already captured by the grade."
--     Outright owners have no mortgage — conventionally read as a strength.
-- ----------------------------------------------------------------------------
SELECT
    homeownership,
    COUNT(*)                                            AS loans,
    SUM(is_impaired)                                    AS impaired,
    ROUND(100.0 * AVG(is_impaired), 2)                  AS impaired_rate_pct,
    ROUND(wilson_low(SUM(is_impaired), COUNT(*)), 2)    AS ci_low,
    ROUND(wilson_high(SUM(is_impaired), COUNT(*)), 2)   AS ci_high,
    ROUND(AVG(interest_rate), 2)                        AS avg_coupon_pct,
    ROUND(AVG(annual_income), 0)                        AS avg_income_usd,
    ROUND(SUM(balance) / 1e6, 1)                        AS balance_musd
FROM loans
GROUP BY homeownership
ORDER BY impaired_rate_pct DESC;
