"""
01_build_db.py
==============
Loads the raw LendingClub Q1-2018 origination extract into a DuckDB database,
applies cleaning rules, and derives the analysis features used downstream.

Run:  python python/01_build_db.py

Creates: data/lending.duckdb
  - raw_loans        : untouched source rows
  - loans            : cleaned + feature-engineered analysis table
  - v_portfolio      : view with credit-economics fields attached
"""

from pathlib import Path
import duckdb
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "loans_full_schema.csv"
DB = ROOT / "data" / "lending.duckdb"

# ----------------------------------------------------------------------------
# Credit-economics assumptions. Every one of these is a business input, not a
# statistical estimate, so they live in one place and are documented in the
# README. Sensitivity to the roll rates is tested in 03_economics.py.
# ----------------------------------------------------------------------------
ASSUMPTIONS = {
    # Probability that a loan in each delinquency bucket eventually charges off.
    # Industry roll-rate convention for unsecured consumer instalment credit.
    "roll_grace": 0.30,          # In Grace Period  (1-15 days past due)
    "roll_late_16_30": 0.45,     # Late (16-30 days)
    "roll_late_31_120": 0.70,    # Late (31-120 days)
    "roll_charged_off": 1.00,    # Already charged off
    "lgd": 0.85,                 # Loss given default, unsecured consumer
    "cost_of_funds": 0.030,      # Annual funding cost
    "servicing_cost": 0.010,     # Annual servicing / platform cost
    "lifetime_co_anchor": 0.090, # Portfolio lifetime gross charge-off anchor
    "wal_36m": 1.6,              # Weighted-average life, 36-month loans (years)
    "wal_60m": 2.6,              # Weighted-average life, 60-month loans (years)
}

IMPAIRED_STATUSES = [
    "Charged Off",
    "Late (31-120 days)",
    "Late (16-30 days)",
    "In Grace Period",
]

ELEVATED_PURPOSES = ["house", "medical", "major_purchase", "car", "moving"]


def load_raw() -> pd.DataFrame:
    if not RAW.exists():
        raise FileNotFoundError(
            f"{RAW} not found. Download it with:\n"
            "  curl -o data/raw/loans_full_schema.csv \\\n"
            "    https://raw.githubusercontent.com/vincentarelbundock/Rdatasets"
            "/master/csv/openintro/loans_full_schema.csv"
        )
    df = pd.read_csv(RAW)
    df = df.rename(columns={"rownames": "loan_id"})
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Cleaning rules. Each one is deliberate and reversible."""
    out = df.copy()

    # 1. annual_income == 0 is not a real income; it breaks every ratio that
    #    uses it as a denominator. Set to NULL rather than dropping the row so
    #    the loan still counts in volume-based metrics.
    out["annual_income"] = out["annual_income"].replace(0, np.nan)

    # 2. debt_to_income is reported up to 469%. Values above 100% are almost
    #    always a joint-application artefact or a data error. Flag, don't drop.
    out["dti_implausible"] = (out["debt_to_income"] > 100).astype(int)

    # 3. Issue month to a real date so cohorts can be ordered.
    out["issue_date"] = pd.to_datetime(out["issue_month"], format="%b-%Y")

    return out


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    """Derive the analysis features."""
    a = ASSUMPTIONS
    out = df.copy()

    # --- outcome definition ---------------------------------------------------
    # The book is only ~4 months seasoned, so ultimate default is unobservable.
    # The analysable outcome is EARLY IMPAIRMENT: any loan that has already
    # missed a payment. This is the standard early-warning metric for a fresh
    # vintage.
    out["is_impaired"] = out["loan_status"].isin(IMPAIRED_STATUSES).astype(int)
    out["is_serious"] = out["loan_status"].isin(
        ["Charged Off", "Late (31-120 days)"]
    ).astype(int)

    # --- months on book -------------------------------------------------------
    # Payments made is the cleanest available proxy for seasoning.
    out["payments_made"] = (out["paid_total"] / out["installment"]).round(1)

    # --- borrower features ----------------------------------------------------
    out["credit_utilization"] = np.where(
        out["total_credit_limit"] > 0,
        out["total_credit_utilized"] / out["total_credit_limit"],
        np.nan,
    )
    out["payment_to_income"] = (out["installment"] * 12) / out["annual_income"]
    out["credit_history_years"] = out["issue_date"].dt.year - out["earliest_credit_line"]

    # --- segmentation flags used by the decision framework --------------------
    out["income_verified_flag"] = (out["verified_income"] == "Verified").astype(int)
    out["is_prime"] = out["grade"].isin(["A", "B"]).astype(int)
    out["elevated_purpose_flag"] = out["loan_purpose"].isin(ELEVATED_PURPOSES).astype(int)
    out["joint_flag"] = (out["application_type"] == "joint").astype(int)
    out["outright_owner_flag"] = (out["homeownership"] == "OWN").astype(int)

    # --- credit economics -----------------------------------------------------
    roll_map = {
        "In Grace Period": a["roll_grace"],
        "Late (16-30 days)": a["roll_late_16_30"],
        "Late (31-120 days)": a["roll_late_31_120"],
        "Charged Off": a["roll_charged_off"],
    }
    out["roll_to_co"] = out["loan_status"].map(roll_map).fillna(0.0)

    # Early-warning loss: principal at risk today, weighted by the probability
    # it rolls to charge-off, net of recoveries.
    out["ew_loss_usd"] = out["balance"] * out["roll_to_co"] * a["lgd"]

    out["wal_years"] = np.where(out["term"] == 36, a["wal_36m"], a["wal_60m"])

    return out


def attach_lifetime_scaling(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert the observed early-warning loss into an annualised loss rate.

    A 4-month-old book has only realised a fraction of its lifetime losses. We
    scale the observed early-warning loss by a single portfolio-level constant k,
    calibrated so that the portfolio's implied LIFETIME gross charge-off equals
    the 9.0% anchor (the assumed loss expectation for a comparable grade mix).

    Because k is a single scalar applied to every loan, it moves all segments
    together: it sets the ABSOLUTE level of loss, never the RANKING of segments.
    03_economics.py demonstrates this with a sensitivity test.
    """
    a = ASSUMPTIONS
    out = df.copy()
    portfolio_ewlr = out["ew_loss_usd"].sum() / out["balance"].sum()
    k = (a["lifetime_co_anchor"] * a["lgd"]) / portfolio_ewlr
    out["seasoning_multiplier"] = k
    out["lifetime_loss_usd"] = out["ew_loss_usd"] * k
    out["annual_loss_usd"] = out["lifetime_loss_usd"] / out["wal_years"]

    # P&L per loan, annualised, as a share of outstanding balance
    out["revenue_usd"] = out["balance"] * out["interest_rate"] / 100
    out["cost_usd"] = out["balance"] * (a["cost_of_funds"] + a["servicing_cost"])
    out["net_margin_usd"] = out["revenue_usd"] - out["cost_usd"] - out["annual_loss_usd"]
    return out


def main() -> None:
    print("Loading raw extract ...")
    df = load_raw()
    print(f"  {len(df):,} loans x {df.shape[1]} columns")

    df_clean = clean(df)
    df_feat = engineer(df_clean)
    df_final = attach_lifetime_scaling(df_feat)

    k = df_final["seasoning_multiplier"].iloc[0]
    print(f"  seasoning multiplier k = {k:.2f}")

    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))

    con.execute("CREATE TABLE raw_loans AS SELECT * FROM df")
    con.execute("CREATE TABLE loans AS SELECT * FROM df_final")

    con.execute(
        """
        CREATE VIEW v_portfolio AS
        SELECT
            loan_id, grade, sub_grade, term, interest_rate, loan_amount, balance,
            installment, loan_status, is_impaired, is_serious,
            loan_purpose, application_type, homeownership, verified_income,
            annual_income, debt_to_income, credit_utilization, payment_to_income,
            inquiries_last_12m, accounts_opened_24m, delinq_2y, credit_history_years,
            income_verified_flag, is_prime, elevated_purpose_flag,
            joint_flag, outright_owner_flag,
            issue_date, payments_made,
            ew_loss_usd, annual_loss_usd, revenue_usd, cost_usd, net_margin_usd
        FROM loans
        """
    )

    # Reference table so the SQL layer can read the assumptions too.
    assumptions = pd.DataFrame(
        [{"parameter": k_, "value": v} for k_, v in ASSUMPTIONS.items()]
    )
    con.execute("CREATE TABLE assumptions AS SELECT * FROM assumptions")

    n, bal, orig, imp = con.execute(
        """
        SELECT COUNT(*), SUM(balance), SUM(loan_amount), AVG(is_impaired)
        FROM loans
        """
    ).fetchone()
    print(f"\nDatabase written to {DB}")
    print(f"  loans              {n:,}")
    print(f"  originated         ${orig/1e6:,.1f}M")
    print(f"  outstanding        ${bal/1e6:,.1f}M")
    print(f"  early impairment   {imp*100:.2f}% of accounts")
    con.close()


if __name__ == "__main__":
    main()
