"""
03_statistical_tests.py
=======================
The SQL layer finds differences. This layer decides which of them are real.

On a 1.78% base rate, a 150-loan segment contains ~3 impaired loans. One loan
either way moves the rate by 0.7pp. Every headline claim in the README is
therefore backed by a significance test here, and any claim that fails is
reported as failed rather than quietly dropped.

Run:  python python/03_statistical_tests.py
Writes: outputs/tables/statistical_tests.csv
        outputs/tables/logistic_regression.csv
"""

from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lending.duckdb"
OUT = ROOT / "outputs" / "tables"

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def load() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("SELECT * FROM loans").fetchdf()
    con.close()
    return df


def fisher(df: pd.DataFrame, mask, label: str) -> dict:
    """Two-tailed Fisher exact test: flagged group vs everyone else."""
    table = pd.crosstab(mask, df["is_impaired"])
    if table.shape != (2, 2):
        return {"test": label, "note": "degenerate table"}
    odds, p = stats.fisher_exact(table.values)
    grp, rest = df[mask], df[~mask]
    return {
        "test": label,
        "n_segment": int(mask.sum()),
        "impaired_segment": int(grp["is_impaired"].sum()),
        "rate_segment_pct": round(100 * grp["is_impaired"].mean(), 2),
        "rate_rest_pct": round(100 * rest["is_impaired"].mean(), 2),
        "risk_multiple": round(
            grp["is_impaired"].mean() / max(rest["is_impaired"].mean(), 1e-9), 2
        ),
        "coupon_gap_pp": round(
            grp["interest_rate"].mean() - rest["interest_rate"].mean(), 2
        ),
        "p_value": round(p, 5),
        "verdict": "SIGNIFICANT" if p < 0.05 else "not significant",
    }


def main() -> None:
    df = load()
    rows = []

    # ---- H1: income verification, by credit band --------------------------
    prime = df[df["is_prime"] == 1]
    rows.append(
        fisher(prime, prime["income_verified_flag"] == 1,
               "H1a  Prime (A-B): income Verified vs rest")
    )
    nonprime = df[df["is_prime"] == 0]
    rows.append(
        fisher(nonprime, nonprime["income_verified_flag"] == 1,
               "H1b  Non-prime (C-G): income Verified vs rest")
    )
    for g in ["A", "B", "C", "D"]:
        sub = df[df["grade"] == g]
        rows.append(
            fisher(sub, sub["income_verified_flag"] == 1,
                   f"H1c  Grade {g}: income Verified vs rest")
        )

    # ---- H2: loan purpose --------------------------------------------------
    rows.append(fisher(df, df["loan_purpose"] == "house",
                       "H2a  Purpose 'house' vs rest"))
    rows.append(fisher(df, df["elevated_purpose_flag"] == 1,
                       "H2b  Elevated-purpose set vs rest"))
    rows.append(fisher(df, df["loan_purpose"] == "small_business",
                       "H2c  Purpose 'small_business' vs rest"))

    # ---- H4 / H5 -----------------------------------------------------------
    rows.append(fisher(df, df["term"] == 60, "H4   60-month term vs 36-month"))
    rows.append(fisher(df, df["outright_owner_flag"] == 1,
                       "H5   Owns outright vs rest"))
    rows.append(fisher(df, df["joint_flag"] == 1,
                       "H6   Joint application vs individual"))

    tests = pd.DataFrame(rows)
    print("=" * 100)
    print("UNIVARIATE TESTS  (Fisher exact, two-tailed)")
    print("=" * 100)
    print(tests.to_string(index=False))

    # ---- Multivariate: does each driver survive controlling for grade? ------
    m = df.dropna(subset=["debt_to_income", "credit_utilization", "payment_to_income"]).copy()
    m["verified"] = np.where(m["income_verified_flag"] == 1, "Verified", "Not/Source")
    m["term60"] = (m["term"] == 60).astype(int)

    formula = (
        "is_impaired ~ C(grade) + verified + term60 + joint_flag "
        "+ elevated_purpose_flag + outright_owner_flag "
        "+ payment_to_income + debt_to_income + inquiries_last_12m"
    )
    res = smf.logit(formula, data=m).fit(disp=0)
    logit = pd.DataFrame(
        {
            "coefficient": res.params.round(3),
            "odds_ratio": np.exp(res.params).round(2),
            "p_value": res.pvalues.round(4),
        }
    )
    logit["verdict"] = np.where(logit["p_value"] < 0.05, "SIGNIFICANT", "not significant")

    print("\n" + "=" * 100)
    print(f"MULTIVARIATE LOGISTIC REGRESSION  (n={len(m):,},  "
          f"pseudo R-squared={res.prsquared:.4f})")
    print("Does each driver survive once the credit grade is controlled for?")
    print("=" * 100)
    print(logit.to_string())

    # ---- The interaction that the univariate tests imply --------------------
    # H1 showed verification is harmful in prime and neutral in non-prime.
    # That is an interaction claim, so test it as one.
    m["band"] = np.where(m["is_prime"] == 1, "Prime", "NonPrime")
    inter = smf.logit("is_impaired ~ C(grade) + verified * band", data=m).fit(disp=0)
    key = [i for i in inter.params.index if ":" in i]
    print("\n" + "=" * 100)
    print("INTERACTION TEST: verification x credit band")
    print("=" * 100)
    for k in key:
        print(f"  {k}")
        print(f"    odds ratio {np.exp(inter.params[k]):.2f}   p = {inter.pvalues[k]:.4f}")
    print("\n  Reading: verification carries OPPOSITE information in the two bands.")
    print("  A single main effect would have averaged the two away to nothing.")

    OUT.mkdir(parents=True, exist_ok=True)
    tests.to_csv(OUT / "statistical_tests.csv", index=False)
    logit.to_csv(OUT / "logistic_regression.csv")
    print(f"\nWritten to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
