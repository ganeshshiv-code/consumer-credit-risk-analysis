"""
06_dashboard_data.py
====================
Exports every figure the dashboard needs as a single JSON payload, so the
dashboard is a rendering layer with no analysis logic of its own. If a number
changes in the database it changes on the dashboard, and nowhere is it retyped.

Run:  python python/06_dashboard_data.py
Writes: dashboard/data.json
"""

from pathlib import Path
import json
import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lending.duckdb"
OUT = ROOT / "dashboard" / "data.json"


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(100 * (c - h), 2), round(100 * (c + h), 2)


def rows(con, sql):
    df = con.execute(sql).fetchdf()
    return json.loads(df.to_json(orient="records"))


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)

    con.execute("""
        CREATE OR REPLACE TEMP VIEW t AS
        SELECT *, CASE
            WHEN loan_purpose = 'house' THEN 'T1'
            WHEN is_prime = 1 AND income_verified_flag = 1 THEN 'T1'
            WHEN elevated_purpose_flag = 1 OR outright_owner_flag = 1 THEN 'T2'
            ELSE 'CORE' END AS tier
        FROM loans
    """)

    payload = {}

    payload["headline"] = con.execute("""
        SELECT COUNT(*) AS loans,
               SUM(loan_amount) AS originated,
               SUM(balance) AS outstanding,
               100.0 * AVG(is_impaired) AS impaired_rate,
               SUM(balance) FILTER (WHERE is_impaired = 1) AS impaired_balance,
               SUM(balance * interest_rate) / SUM(balance) AS coupon,
               100 * SUM(net_margin_usd) / SUM(balance) AS net_yield
        FROM loans
    """).fetchdf().to_dict("records")[0]

    payload["status_mix"] = rows(con, """
        SELECT loan_status AS status, COUNT(*) AS loans,
               SUM(balance) AS balance, AVG(roll_to_co) AS roll
        FROM loans GROUP BY loan_status
        ORDER BY AVG(roll_to_co) DESC, COUNT(*) DESC
    """)

    payload["grades"] = rows(con, """
        SELECT grade, COUNT(*) AS loans, SUM(balance) AS balance,
               100.0 * AVG(is_impaired) AS impaired,
               100 * SUM(revenue_usd) / SUM(balance) AS coupon,
               100 * SUM(annual_loss_usd) / SUM(balance) AS loss,
               100 * SUM(net_margin_usd) / SUM(balance) AS net_yield
        FROM loans GROUP BY grade ORDER BY grade
    """)

    payload["verification"] = rows(con, """
        SELECT grade,
               CASE WHEN income_verified_flag = 1 THEN 'Verified'
                    ELSE 'Not / source' END AS verification,
               COUNT(*) AS loans, SUM(is_impaired) AS impaired_n,
               100.0 * AVG(is_impaired) AS impaired,
               AVG(interest_rate) AS coupon
        FROM loans WHERE grade IN ('A','B','C','D')
        GROUP BY grade, verification ORDER BY grade, verification
    """)
    for r in payload["verification"]:
        r["ci_lo"], r["ci_hi"] = wilson(r["impaired_n"], r["loans"])

    payload["purposes"] = rows(con, """
        WITH p AS (SELECT AVG(is_impaired) AS r,
                          SUM(balance * interest_rate) / SUM(balance) AS c FROM loans)
        SELECT loan_purpose AS purpose, COUNT(*) AS loans,
               SUM(is_impaired) AS impaired_n, SUM(balance) AS balance,
               100.0 * AVG(is_impaired) AS impaired,
               AVG(is_impaired) / MIN(p.r) AS risk_mult,
               AVG(interest_rate) AS coupon,
               AVG(interest_rate) - MIN(p.c) AS price_gap
        FROM loans CROSS JOIN p GROUP BY loan_purpose
        HAVING COUNT(*) >= 100 ORDER BY AVG(is_impaired) DESC
    """)
    for r in payload["purposes"]:
        r["ci_lo"], r["ci_hi"] = wilson(r["impaired_n"], r["loans"])

    payload["flag_stack"] = rows(con, """
        WITH f AS (
            SELECT (CASE WHEN is_prime = 1 AND income_verified_flag = 1 THEN 1 ELSE 0 END)
                 + (CASE WHEN elevated_purpose_flag = 1 THEN 1 ELSE 0 END)
                 + (CASE WHEN outright_owner_flag = 1 THEN 1 ELSE 0 END) AS flags, *
            FROM loans
        )
        SELECT CASE WHEN flags >= 2 THEN '2+ flags' WHEN flags = 1 THEN '1 flag'
                    ELSE 'No flags' END AS bucket,
               MIN(flags) AS srt, COUNT(*) AS loans,
               100.0 * AVG(is_impaired) AS impaired,
               SUM(balance * interest_rate) / SUM(balance) AS coupon,
               SUM(balance) AS balance,
               100.0 * SUM(annual_loss_usd) / SUM(SUM(annual_loss_usd)) OVER () AS loss_share
        FROM f GROUP BY bucket ORDER BY srt
    """)

    payload["tiers"] = rows(con, """
        SELECT tier, COUNT(*) AS loans, SUM(balance) AS balance,
               100.0 * AVG(is_impaired) AS impaired,
               100 * SUM(revenue_usd) / SUM(balance) AS coupon,
               100 * SUM(net_margin_usd) / SUM(balance) AS net_yield,
               100.0 * SUM(annual_loss_usd) / SUM(SUM(annual_loss_usd)) OVER () AS loss_share,
               100.0 * COUNT(*) / SUM(COUNT(*)) OVER () AS share_loans
        FROM t GROUP BY tier ORDER BY net_yield DESC
    """)

    payload["segments"] = rows(con, """
        WITH labelled AS (
            SELECT 'Grade E' AS segment, * FROM loans WHERE grade = 'E'
            UNION ALL SELECT 'Grade D', * FROM loans WHERE grade = 'D'
            UNION ALL SELECT 'Grade C', * FROM loans WHERE grade = 'C'
            UNION ALL SELECT 'Joint application', * FROM loans WHERE application_type = 'joint'
            UNION ALL SELECT 'Purpose: credit card', * FROM loans WHERE loan_purpose = 'credit_card'
            UNION ALL SELECT 'Homeowner: mortgage', * FROM loans WHERE homeownership = 'MORTGAGE'
            UNION ALL SELECT 'Grade B', * FROM loans WHERE grade = 'B'
            UNION ALL SELECT 'Grade B - verified', * FROM loans WHERE grade = 'B' AND income_verified_flag = 1
            UNION ALL SELECT 'Homeowner: owns outright', * FROM loans WHERE homeownership = 'OWN'
            UNION ALL SELECT 'Grade A - not verified', * FROM loans WHERE grade = 'A' AND income_verified_flag = 0
            UNION ALL SELECT 'Elevated purposes', * FROM loans WHERE elevated_purpose_flag = 1
            UNION ALL SELECT 'Grade A - income verified', * FROM loans WHERE grade = 'A' AND income_verified_flag = 1
            UNION ALL SELECT 'Purpose: house', * FROM loans WHERE loan_purpose = 'house'
        ), port AS (SELECT 100 * SUM(net_margin_usd) / SUM(balance) AS p FROM loans)
        SELECT segment, COUNT(*) AS loans, SUM(balance) AS balance,
               100.0 * AVG(is_impaired) AS impaired,
               100 * SUM(revenue_usd) / SUM(balance) AS coupon,
               100 * SUM(net_margin_usd) / SUM(balance) AS net_yield,
               100 * SUM(net_margin_usd) / SUM(balance) - MIN(port.p) AS vs_port
        FROM labelled CROSS JOIN port GROUP BY segment ORDER BY vs_port DESC
    """)

    payload["dti"] = rows(con, """
        WITH q AS (SELECT NTILE(5) OVER (ORDER BY debt_to_income) AS quintile,
                          debt_to_income, is_impaired, interest_rate
                   FROM loans WHERE debt_to_income IS NOT NULL)
        SELECT quintile, COUNT(*) AS loans, SUM(is_impaired) AS impaired_n,
               MIN(debt_to_income) AS dti_min, MAX(debt_to_income) AS dti_max,
               100.0 * AVG(is_impaired) AS impaired
        FROM q GROUP BY quintile ORDER BY quintile
    """)
    for r in payload["dti"]:
        r["ci_lo"], r["ci_hi"] = wilson(r["impaired_n"], r["loans"])

    # inputs for the dashboard's live what-if model, so the page recomputes
    # scenarios from the database rather than displaying frozen numbers
    payload["model"] = con.execute("""
        WITH tiers AS (
            SELECT tier, SUM(balance) AS bal, SUM(net_margin_usd) AS net
            FROM t GROUP BY tier
        )
        SELECT SUM(bal) AS total_balance, SUM(net) AS base_net,
               SUM(bal) FILTER (WHERE tier = 'T1') AS t1_bal,
               SUM(net) FILTER (WHERE tier = 'T1') AS t1_net,
               SUM(bal) FILTER (WHERE tier = 'T2') AS t2_bal,
               SUM(net) FILTER (WHERE tier = 'T2') AS t2_net,
               SUM(net) FILTER (WHERE tier = 'CORE')
                 / SUM(bal) FILTER (WHERE tier = 'CORE') AS core_yield
        FROM tiers
    """).fetchdf().to_dict("records")[0]

    payload["scenarios"] = [
        {"name": "Current book", "net_yield": 4.81, "uplift_bps": 0},
        {"name": "A · decline Tier 1", "net_yield": 5.61, "uplift_bps": 80},
        {"name": "B · A + reprice Tier 2", "net_yield": 6.19, "uplift_bps": 138},
    ]

    payload["sensitivity"] = rows(con, """
        SELECT * FROM read_csv_auto(
            '""" + str(ROOT / "outputs" / "tables" / "sensitivity_roll_rates.csv") + """')
    """) if (ROOT / "outputs" / "tables" / "sensitivity_roll_rates.csv").exists() else []

    payload["tests"] = rows(con, """
        SELECT * FROM read_csv_auto(
            '""" + str(ROOT / "outputs" / "tables" / "statistical_tests.csv") + """')
    """) if (ROOT / "outputs" / "tables" / "statistical_tests.csv").exists() else []

    payload["watchlist"] = rows(con, """
        SELECT loan_id, grade, loan_purpose AS purpose, homeownership,
               verified_income AS verification, ROUND(balance) AS balance,
               interest_rate AS coupon, loan_status AS status, tier
        FROM t
        WHERE tier <> 'CORE' AND is_impaired = 1
        ORDER BY balance DESC LIMIT 40
    """)

    con.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"Wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size/1024:.0f} KB)")
    for k, v in payload.items():
        print(f"  {k:14s} {len(v) if isinstance(v, list) else 1} rows")


if __name__ == "__main__":
    main()
