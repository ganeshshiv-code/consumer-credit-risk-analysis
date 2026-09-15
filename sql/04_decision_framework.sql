-- ============================================================================
-- 04_decision_framework.sql
-- Purpose: convert the findings into an underwriting overlay the credit team
--          can actually apply, then size the money it moves.
--
-- Tier 1 (DECLINE)  : segments whose net yield is negative under every roll
--                     assumption tested. The book pays to own them.
-- Tier 2 (REPRICE)  : segments that earn a positive but sub-portfolio yield.
--                     Price the risk instead of refusing it.
-- Core   (GROW)     : everything else.
-- Engine:  DuckDB
-- ============================================================================


-- ----------------------------------------------------------------------------
-- The overlay itself, as a reusable view.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_tiered AS
SELECT
    *,
    CASE
        -- Tier 1: the two segments that fail outright
        WHEN loan_purpose = 'house'                                   THEN 'T1_DECLINE'
        WHEN is_prime = 1 AND income_verified_flag = 1                THEN 'T1_DECLINE'
        -- Tier 2: elevated risk, inadequately priced, but still positive
        WHEN elevated_purpose_flag = 1                                THEN 'T2_REPRICE'
        WHEN outright_owner_flag = 1                                  THEN 'T2_REPRICE'
        ELSE 'CORE'
    END AS decision_tier
FROM loans;


-- ----------------------------------------------------------------------------
-- Q1. Size each tier: accounts, balance, risk, and share of modelled loss.
-- ----------------------------------------------------------------------------
SELECT
    decision_tier,
    COUNT(*)                                                       AS loans,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)             AS pct_of_loans,
    ROUND(SUM(balance) / 1e6, 2)                                   AS balance_musd,
    ROUND(100.0 * SUM(balance) / SUM(SUM(balance)) OVER (), 1)     AS pct_of_balance,
    ROUND(100.0 * AVG(is_impaired), 2)                             AS impaired_rate_pct,
    ROUND(100 * SUM(revenue_usd)     / SUM(balance), 2)            AS coupon_pct,
    ROUND(100 * SUM(annual_loss_usd) / SUM(balance), 2)            AS annual_loss_pct,
    ROUND(100 * SUM(net_margin_usd)  / SUM(balance), 2)            AS net_yield_pct,
    -- the headline: a quarter of the book carries nearly half the loss
    ROUND(100.0 * SUM(annual_loss_usd)
          / SUM(SUM(annual_loss_usd)) OVER (), 1)                  AS pct_of_total_loss
FROM v_tiered
GROUP BY decision_tier
ORDER BY decision_tier;


-- ----------------------------------------------------------------------------
-- Q2. Scenario model — what the overlay is worth.
--
--   Scenario A: decline Tier 1, redeploy that capital into Core at the Core
--               net yield. No change to Tier 2.
--   Scenario B: Scenario A, plus reprice Tier 2 by +400bps. Assume 35% of
--               those borrowers walk (they can shop elsewhere) and that the
--               freed capital also redeploys into Core.
--
-- The attrition rate is the one genuinely uncertain input, so Q3 flexes it.
-- ----------------------------------------------------------------------------
WITH params AS (
    SELECT 0.0400 AS reprice_premium, 0.35 AS attrition
),
tiers AS (
    SELECT
        decision_tier,
        SUM(balance)          AS balance,
        SUM(net_margin_usd)   AS net_margin
    FROM v_tiered
    GROUP BY decision_tier
),
book AS (
    SELECT
        SUM(balance)                                                   AS total_balance,
        SUM(net_margin)                                                AS base_net,
        SUM(balance)    FILTER (WHERE decision_tier = 'T1_DECLINE')    AS t1_bal,
        SUM(net_margin) FILTER (WHERE decision_tier = 'T1_DECLINE')    AS t1_net,
        SUM(balance)    FILTER (WHERE decision_tier = 'T2_REPRICE')    AS t2_bal,
        SUM(net_margin) FILTER (WHERE decision_tier = 'T2_REPRICE')    AS t2_net,
        SUM(net_margin) FILTER (WHERE decision_tier = 'CORE')
            / SUM(balance) FILTER (WHERE decision_tier = 'CORE')       AS core_yield
    FROM tiers
),
scenarios AS (
    SELECT
        p.*,
        -- A: swap Tier 1 balance for Core-quality balance
        p.base_net - p.t1_net + p.t1_bal * p.core_yield                AS net_a,
        -- B: A, then reprice Tier 2; the 35% who leave are redeployed to Core
        (p.base_net - p.t1_net + p.t1_bal * p.core_yield)
            - p.t2_net
            + (1 - pr.attrition) * (p.t2_net + p.t2_bal * pr.reprice_premium)
            + pr.attrition * p.t2_bal * p.core_yield                   AS net_b
    FROM book p CROSS JOIN params pr
)
SELECT
    ROUND(total_balance / 1e6, 1)                               AS book_musd,
    ROUND(100 * base_net / total_balance, 2)                    AS baseline_net_yield_pct,
    ROUND(100 * net_a    / total_balance, 2)                    AS scenario_a_net_yield_pct,
    ROUND(100 * net_b    / total_balance, 2)                    AS scenario_b_net_yield_pct,
    ROUND(10000 * (net_a - base_net) / total_balance, 0)        AS scenario_a_uplift_bps,
    ROUND(10000 * (net_b - base_net) / total_balance, 0)        AS scenario_b_uplift_bps,
    ROUND((net_a - base_net) / 1e3, 0)                          AS scenario_a_gain_kusd,
    ROUND((net_b - base_net) / 1e3, 0)                          AS scenario_b_gain_kusd,
    -- what the same overlay earns on a $500M annual origination programme
    ROUND(500 * (net_b - base_net) / total_balance, 2)          AS gain_on_500m_musd
FROM scenarios;


-- ----------------------------------------------------------------------------
-- Q3. Attrition sensitivity — how wrong can the behavioural assumption be
--     before Scenario B stops beating Scenario A?
-- ----------------------------------------------------------------------------
WITH grid AS (SELECT UNNEST([0.0, 0.20, 0.35, 0.50, 0.70, 1.0]) AS attrition),
tiers AS (
    SELECT decision_tier, SUM(balance) AS balance, SUM(net_margin_usd) AS net_margin
    FROM v_tiered GROUP BY decision_tier
),
book AS (
    SELECT
        SUM(balance) AS total_balance, SUM(net_margin) AS base_net,
        SUM(balance)    FILTER (WHERE decision_tier = 'T1_DECLINE') AS t1_bal,
        SUM(net_margin) FILTER (WHERE decision_tier = 'T1_DECLINE') AS t1_net,
        SUM(balance)    FILTER (WHERE decision_tier = 'T2_REPRICE') AS t2_bal,
        SUM(net_margin) FILTER (WHERE decision_tier = 'T2_REPRICE') AS t2_net,
        SUM(net_margin) FILTER (WHERE decision_tier = 'CORE')
            / SUM(balance) FILTER (WHERE decision_tier = 'CORE')    AS core_yield
    FROM tiers
)
SELECT
    ROUND(100 * g.attrition, 0)                                        AS attrition_pct,
    ROUND(10000 * (
        ((p.base_net - p.t1_net + p.t1_bal * p.core_yield)
          - p.t2_net
          + (1 - g.attrition) * (p.t2_net + p.t2_bal * 0.04)
          + g.attrition * p.t2_bal * p.core_yield) - p.base_net
    ) / p.total_balance, 0)                                            AS uplift_bps
FROM grid g CROSS JOIN book p
ORDER BY g.attrition;


-- ----------------------------------------------------------------------------
-- Q4. The operational output: a monitoring list the credit team runs monthly.
--     Every live loan that carries an uncompensated-risk flag, worst first.
-- ----------------------------------------------------------------------------
SELECT
    loan_id,
    grade,
    loan_purpose,
    homeownership,
    verified_income,
    ROUND(balance, 0)                                   AS balance_usd,
    interest_rate                                       AS coupon_pct,
    loan_status,
    decision_tier,
    -- plain-language reason, so the list is actionable without a data analyst
    TRIM(CONCAT_WS(' + ',
        CASE WHEN is_prime = 1 AND income_verified_flag = 1
             THEN 'prime+verified' END,
        CASE WHEN loan_purpose = 'house'     THEN 'purpose:house' END,
        CASE WHEN elevated_purpose_flag = 1 AND loan_purpose <> 'house'
             THEN 'purpose:elevated' END,
        CASE WHEN outright_owner_flag = 1    THEN 'owns outright' END
    ))                                                  AS flags
FROM v_tiered
WHERE decision_tier <> 'CORE'
  AND loan_status <> 'Fully Paid'
ORDER BY
    CASE decision_tier WHEN 'T1_DECLINE' THEN 1 ELSE 2 END,
    balance DESC
LIMIT 25;
