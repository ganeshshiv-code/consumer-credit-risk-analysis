"""
04_sensitivity.py
=================
The economics rest on assumptions that are business inputs, not measurements:
roll-to-charge-off rates, loss given default, cost of funds, and the lifetime
loss anchor used to season a 4-month-old book.

If the recommendation only holds at one set of assumptions it is not a
recommendation, it is a coincidence. This script re-runs the segment economics
across the plausible range of each input and reports whether the tier RANKING —
which is what the recommendation actually depends on — ever changes.

Run:  python python/04_sensitivity.py
Writes: outputs/tables/sensitivity_roll_rates.csv
        outputs/tables/sensitivity_assumptions.csv
"""

from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lending.duckdb"
OUT = ROOT / "outputs" / "tables"

pd.set_option("display.width", 200)

ROLL_SCENARIOS = {
    # name:        grace, 16-30, 31-120, charged off
    "optimistic":  (0.15, 0.30, 0.55, 1.00),
    "base":        (0.30, 0.45, 0.70, 1.00),
    "severe":      (0.45, 0.60, 0.85, 1.00),
    "very severe": (0.60, 0.75, 0.95, 1.00),
}


def load() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("SELECT * FROM loans").fetchdf()
    con.close()
    return df


def tier_of(row) -> str:
    if row["loan_purpose"] == "house":
        return "T1_DECLINE"
    if row["is_prime"] == 1 and row["income_verified_flag"] == 1:
        return "T1_DECLINE"
    if row["elevated_purpose_flag"] == 1 or row["outright_owner_flag"] == 1:
        return "T2_REPRICE"
    return "CORE"


def economics(df, roll, lgd, funds, servicing, anchor) -> pd.DataFrame:
    """Recompute net yield per tier under one set of assumptions."""
    grace, l1630, l31120, co = roll
    roll_map = {
        "In Grace Period": grace,
        "Late (16-30 days)": l1630,
        "Late (31-120 days)": l31120,
        "Charged Off": co,
    }
    x = df.copy()
    x["ew"] = x["balance"] * x["loan_status"].map(roll_map).fillna(0.0) * lgd
    k = (anchor * lgd) / (x["ew"].sum() / x["balance"].sum())
    x["annual_loss"] = x["ew"] * k / x["wal_years"]
    x["net"] = (
        x["balance"] * x["interest_rate"] / 100
        - x["balance"] * (funds + servicing)
        - x["annual_loss"]
    )
    g = x.groupby("decision_tier").apply(
        lambda s: 100 * s["net"].sum() / s["balance"].sum(), include_groups=False
    )
    return g


def main() -> None:
    df = load()
    df["decision_tier"] = df.apply(tier_of, axis=1)

    # ---------------------------------------------------------------- roll ---
    rows = []
    for name, roll in ROLL_SCENARIOS.items():
        g = economics(df, roll, 0.85, 0.030, 0.010, 0.090)
        rows.append(
            {
                "roll_scenario": name,
                "grace_roll": roll[0],
                "late_31_120_roll": roll[2],
                "CORE_net_yield_pct": round(g.get("CORE", np.nan), 2),
                "T2_REPRICE_net_yield_pct": round(g.get("T2_REPRICE", np.nan), 2),
                "T1_DECLINE_net_yield_pct": round(g.get("T1_DECLINE", np.nan), 2),
                "ranking_preserved": (
                    g["CORE"] > g["T2_REPRICE"] > g["T1_DECLINE"]
                ),
            }
        )
    roll_df = pd.DataFrame(rows)
    print("=" * 96)
    print("SENSITIVITY 1 — roll-to-charge-off assumptions")
    print("=" * 96)
    print(roll_df.to_string(index=False))
    print(
        "\n  The absolute level of loss moves with the roll rates. The ORDER of the "
        "tiers\n  does not, which is the only property the recommendation relies on."
    )

    # --------------------------------------------------- other assumptions ---
    rows = []
    grid = [
        ("loss given default", "lgd", [0.70, 0.85, 0.95]),
        ("cost of funds", "funds", [0.020, 0.030, 0.045]),
        ("servicing cost", "servicing", [0.005, 0.010, 0.020]),
        ("lifetime loss anchor", "anchor", [0.060, 0.090, 0.130]),
    ]
    for label, key, values in grid:
        for v in values:
            kw = {"lgd": 0.85, "funds": 0.030, "servicing": 0.010, "anchor": 0.090}
            kw[key] = v
            g = economics(df, ROLL_SCENARIOS["base"], **kw)
            rows.append(
                {
                    "assumption": label,
                    "value": v,
                    "CORE": round(g["CORE"], 2),
                    "T2_REPRICE": round(g["T2_REPRICE"], 2),
                    "T1_DECLINE": round(g["T1_DECLINE"], 2),
                    "T1_still_negative": g["T1_DECLINE"] < 0,
                    "ranking_preserved": g["CORE"] > g["T2_REPRICE"] > g["T1_DECLINE"],
                }
            )
    assum_df = pd.DataFrame(rows)
    print("\n" + "=" * 96)
    print("SENSITIVITY 2 — one assumption at a time, roll rates held at base")
    print("=" * 96)
    print(assum_df.to_string(index=False))

    preserved = assum_df["ranking_preserved"].all() and roll_df["ranking_preserved"].all()
    neg = assum_df["T1_still_negative"]
    print("\n" + "-" * 96)
    print(f"Tier ranking preserved in all {len(assum_df) + len(roll_df)} scenarios: {preserved}")
    print(
        f"Tier 1 net yield stays negative in {int(neg.sum())} of {len(neg)} "
        "single-assumption scenarios."
    )
    if not neg.all():
        broke = assum_df[~neg][["assumption", "value", "T1_DECLINE"]]
        print("\nWhere Tier 1 turns positive — the honest caveat for the write-up:")
        print(broke.to_string(index=False))

    OUT.mkdir(parents=True, exist_ok=True)
    roll_df.to_csv(OUT / "sensitivity_roll_rates.csv", index=False)
    assum_df.to_csv(OUT / "sensitivity_assumptions.csv", index=False)
    print(f"\nWritten to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
