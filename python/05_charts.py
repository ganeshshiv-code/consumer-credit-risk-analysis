"""
05_charts.py
============
Exports the six figures used in the README and the dashboard.

Design rules applied throughout:
  - one measure per axis, never a dual-axis chart (two scales in one frame is
    the single most misleading thing a chart can do). Where risk and price are
    compared, they sit in adjacent panels sharing a category axis.
  - categorical hues assigned in fixed order, never cycled
  - diverging blue/red only where the data genuinely has a zero-crossing
  - confidence intervals drawn wherever a rate is estimated from a small segment
  - recessive grid, thin marks, direct labels instead of a number on every point

Run:  python python/05_charts.py
Writes: outputs/charts/*.png
"""

from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lending.duckdb"
CHARTS = ROOT / "outputs" / "charts"

# --- palette (validated: worst adjacent CVD dE 24.7, normal-vision dE 33.6) ---
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
CRITICAL = "#d03b3b"
GOOD = "#0ca30c"

plt.rcParams.update({
    "font.family": ["DejaVu Sans"],
    "font.size": 10,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 140,
})

PCT = FuncFormatter(lambda v, _: f"{v:.0f}%")


def q(sql: str) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(sql).fetchdf()
    con.close()
    return df


def finish(fig, path: str, note: str | None = None) -> None:
    if note:
        fig.text(0.01, 0.005, note, fontsize=7.5, color=MUTED, ha="left", va="bottom")
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHARTS / path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"  wrote {path}")


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return 100 * (c - h), 100 * (c + h)


# ---------------------------------------------------------------------------
# 1. The headline: risk climbs, price falls.
#    Two measures on different scales -> two panels, one shared category axis.
# ---------------------------------------------------------------------------
def chart_risk_vs_price():
    df = q("""
        WITH f AS (
            SELECT (CASE WHEN is_prime = 1 AND income_verified_flag = 1 THEN 1 ELSE 0 END)
                 + (CASE WHEN elevated_purpose_flag = 1 THEN 1 ELSE 0 END)
                 + (CASE WHEN outright_owner_flag = 1 THEN 1 ELSE 0 END) AS flags,
                   is_impaired, interest_rate, balance
            FROM loans
        )
        SELECT CASE WHEN flags >= 2 THEN '2+ flags' WHEN flags = 1 THEN '1 flag'
                    ELSE 'No flags' END                       AS bucket,
               MIN(flags)                                     AS srt,
               COUNT(*)                                       AS loans,
               100.0 * AVG(is_impaired)                       AS impaired_pct,
               SUM(balance * interest_rate) / SUM(balance)    AS coupon_pct
        FROM f GROUP BY bucket ORDER BY srt
    """)

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.1))
    x = np.arange(len(df))

    ax = axes[0]
    ax.bar(x, df.impaired_pct, width=0.55, color=ORANGE, zorder=3)
    for xi, v in zip(x, df.impaired_pct):
        ax.text(xi, v + 0.12, f"{v:.2f}%", ha="center", va="bottom",
                fontsize=10, color=INK, fontweight="bold")
    ax.set_title("Risk carried", fontsize=11, loc="left", pad=10)
    ax.set_ylabel("Early impairment rate")
    ax.set_ylim(0, max(df.impaired_pct) * 1.3)

    ax = axes[1]
    ax.bar(x, df.coupon_pct, width=0.55, color=BLUE, zorder=3)
    for xi, v in zip(x, df.coupon_pct):
        ax.text(xi, v + 0.15, f"{v:.2f}%", ha="center", va="bottom",
                fontsize=10, color=INK, fontweight="bold")
    ax.set_title("Price charged", fontsize=11, loc="left", pad=10)
    ax.set_ylabel("Average coupon")
    ax.set_ylim(0, max(df.coupon_pct) * 1.25)

    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels([f"{b}\n{n:,} loans" for b, n in zip(df.bucket, df.loans)])
        ax.yaxis.set_major_formatter(PCT)
        ax.grid(axis="y", zorder=0)
        ax.set_axisbelow(True)

    fig.suptitle("Loans carrying uncompensated-risk flags cost more and earn less",
                 fontsize=13, fontweight="bold", x=0.009, ha="left", y=1.02)
    fig.text(0.009, 0.955,
             "Impairment rises 2.7x across the flag buckets while the coupon falls "
             "304bps — the price moves the wrong way.",
             fontsize=9.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0.02, 1, 0.93])
    finish(fig, "01_risk_vs_price.png",
           "Source: LendingClub Q1-2018 originations, n=10,000. Flags: prime+income-verified, "
           "elevated loan purpose, owns home outright.")


# ---------------------------------------------------------------------------
# 2. The verification paradox, with confidence intervals.
# ---------------------------------------------------------------------------
def chart_verification():
    df = q("""
        SELECT grade,
               CASE WHEN income_verified_flag = 1 THEN 'Income verified'
                    ELSE 'Not / source verified' END AS verification,
               COUNT(*) AS n, SUM(is_impaired) AS k,
               100.0 * AVG(is_impaired) AS rate
        FROM loans WHERE grade IN ('A','B','C','D')
        GROUP BY grade, verification ORDER BY grade, verification
    """)
    lo, hi = zip(*[wilson(k, n) for k, n in zip(df.k, df.n)])
    df["lo"], df["hi"] = lo, hi

    grades = ["A", "B", "C", "D"]
    fig, ax = plt.subplots(figsize=(9.2, 4.4))
    w = 0.34
    x = np.arange(len(grades))

    for i, (label, color) in enumerate(
        [("Not / source verified", BLUE), ("Income verified", ORANGE)]
    ):
        sub = df[df.verification == label].set_index("grade").reindex(grades)
        pos = x + (i - 0.5) * (w + 0.02)
        ax.bar(pos, sub.rate, width=w, color=color, label=label, zorder=3)
        ax.errorbar(pos, sub.rate,
                    yerr=[sub.rate - sub.lo, sub.hi - sub.rate],
                    fmt="none", ecolor=INK_2, elinewidth=1.2, capsize=4, zorder=4)
        for p, v, h in zip(pos, sub.rate, sub.hi):
            ax.text(p, h + 0.16, f"{v:.2f}%", ha="center", va="bottom",
                    fontsize=9, color=INK)

    ax.set_xticks(x)
    ax.set_xticklabels([f"Grade {g}" for g in grades])
    ax.set_ylabel("Early impairment rate")
    ax.yaxis.set_major_formatter(PCT)
    ax.grid(axis="y", zorder=0)
    ax.set_axisbelow(True)
    ax.set_ylim(0, 7.6)
    ax.legend(frameon=False, loc="upper left", fontsize=9.5)

    ax.annotate("5.4x the risk\nfor 13bps more coupon",
                xy=(0.38, 4.35), xytext=(0.66, 6.30),
                fontsize=9.5, color=CRITICAL, fontweight="bold", ha="left",
                arrowprops=dict(arrowstyle="->", color=CRITICAL, lw=1.4,
                                connectionstyle="arc3,rad=0.15"))
    ax.annotate("signal is gone\nby grade C",
                xy=(2.36, 3.35), xytext=(2.44, 6.30),
                fontsize=9.5, color=MUTED, ha="left",
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.1,
                                connectionstyle="arc3,rad=-0.15"))

    fig.suptitle("Income verification signals risk in prime grades — and nothing below",
                 fontsize=13, fontweight="bold", x=0.009, ha="left", y=1.02)
    fig.text(0.009, 0.955,
             "Bars show early impairment; whiskers are Wilson 95% intervals. "
             "Interaction with credit band: odds ratio 3.3, p=0.0007.",
             fontsize=9.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0.02, 1, 0.93])
    finish(fig, "02_verification_paradox.png",
           "Source: LendingClub Q1-2018 originations. Grade A verified n=352; "
           "Fisher exact p=0.0006.")


# ---------------------------------------------------------------------------
# 3. Loan purpose: risk against price, one point per purpose.
# ---------------------------------------------------------------------------
def chart_purpose_quadrant():
    df = q("""
        WITH p AS (
            SELECT AVG(is_impaired) AS r,
                   SUM(balance * interest_rate) / SUM(balance) AS c FROM loans
        )
        SELECT loan_purpose, COUNT(*) AS loans, SUM(balance) AS balance,
               AVG(is_impaired) / MIN(p.r)                              AS risk_mult,
               AVG(interest_rate) - MIN(p.c)                            AS price_gap,
               100.0 * AVG(is_impaired)                                 AS rate
        FROM loans CROSS JOIN p
        GROUP BY loan_purpose HAVING COUNT(*) >= 100
    """)

    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    # shade only the true danger quadrant: riskier than the book AND cheaper
    ax.add_patch(plt.Rectangle((1, -2.2), 3.0, 2.2, color=CRITICAL,
                               alpha=0.05, zorder=0, linewidth=0))
    ax.axhline(0, color=AXIS, lw=1.1, zorder=2)
    ax.axvline(1, color=AXIS, lw=1.1, zorder=2)

    sizes = 120 + 1400 * (df.balance / df.balance.max())
    danger = (df.risk_mult > 1) & (df.price_gap < 0)
    ax.scatter(df.risk_mult[~danger], df.price_gap[~danger], s=sizes[~danger],
               color=BLUE, alpha=0.75, edgecolor=SURFACE, linewidth=2, zorder=3)
    ax.scatter(df.risk_mult[danger], df.price_gap[danger], s=sizes[danger],
               color=ORANGE, alpha=0.85, edgecolor=SURFACE, linewidth=2, zorder=3)

    # hand-placed labels: a scatter this dense collides under any automatic rule
    offsets = {
        "credit_card":        (0.00,  0.30, "center", "bottom"),
        "debt_consolidation": (0.12,  0.30, "center", "bottom"),
        "small_business":     (-0.11, -0.36, "right", "top"),
        "other":              (0.08,  0.12, "left", "bottom"),
        "home_improvement":   (0.00, -0.20, "center", "top"),
        "major_purchase":     (-0.05, -0.20, "center", "top"),
        "car":                (0.02,  0.20, "center", "bottom"),
        "medical":            (0.00,  0.20, "center", "bottom"),
        "house":              (-0.10,  0.02, "right", "center"),
    }
    for _, r in df.iterrows():
        dx, dy, ha, va = offsets.get(r.loan_purpose, (0, 0.2, "center", "bottom"))
        ax.text(r.risk_mult + dx, r.price_gap + dy,
                r.loan_purpose.replace("_", " "),
                ha=ha, va=va, fontsize=9, color=INK)

    ax.text(1.10, -2.10, "UNCOMPENSATED — riskier than the book, cheaper than the book",
            ha="left", va="bottom", fontsize=9, color=CRITICAL, fontweight="bold")
    ax.set_xlabel("Early impairment relative to portfolio  (1.0 = portfolio average)")
    ax.set_ylabel("Coupon vs portfolio average")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.1f}pp"))
    ax.set_xlim(0.4, 3.9)
    ax.set_ylim(-2.2, 1.3)
    ax.grid(zorder=0)
    ax.set_axisbelow(True)

    fig.suptitle("Loan purpose carries risk that the pricing engine never sees",
                 fontsize=13, fontweight="bold", x=0.009, ha="left", y=1.0)
    fig.text(0.009, 0.94,
             "Bubble area is outstanding balance. Purposes below the horizontal line "
             "are priced under the book average.",
             fontsize=9.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0.02, 1, 0.92])
    finish(fig, "03_purpose_quadrant.png",
           "Source: LendingClub Q1-2018 originations. Purposes with >=100 loans. "
           "'house' vs rest: 3.9x risk, Fisher p=0.0004.")


# ---------------------------------------------------------------------------
# 4. Segment league table — diverging, because the data crosses zero.
# ---------------------------------------------------------------------------
def chart_segment_league():
    df = q("""
        WITH labelled AS (
            SELECT 'Grade E' AS segment, * FROM loans WHERE grade = 'E'
            UNION ALL SELECT 'Grade D', * FROM loans WHERE grade = 'D'
            UNION ALL SELECT 'Purpose: credit card', * FROM loans WHERE loan_purpose = 'credit_card'
            UNION ALL SELECT 'Joint application', * FROM loans WHERE application_type = 'joint'
            UNION ALL SELECT 'Homeowner: mortgage', * FROM loans WHERE homeownership = 'MORTGAGE'
            UNION ALL SELECT 'Homeowner: owns outright', * FROM loans WHERE homeownership = 'OWN'
            UNION ALL SELECT 'Grade B - verified', * FROM loans WHERE grade = 'B' AND income_verified_flag = 1
            UNION ALL SELECT 'Grade A - not verified', * FROM loans WHERE grade = 'A' AND income_verified_flag = 0
            UNION ALL SELECT 'Elevated purposes', * FROM loans WHERE elevated_purpose_flag = 1
            UNION ALL SELECT 'Grade A - income verified', * FROM loans WHERE grade = 'A' AND income_verified_flag = 1
            UNION ALL SELECT 'Purpose: house', * FROM loans WHERE loan_purpose = 'house'
        ), port AS (SELECT 100 * SUM(net_margin_usd) / SUM(balance) AS p FROM loans)
        SELECT segment, COUNT(*) AS loans, SUM(balance) / 1e6 AS bal,
               100 * SUM(net_margin_usd) / SUM(balance) AS net_yield,
               100 * SUM(net_margin_usd) / SUM(balance) - MIN(port.p) AS vs_port
        FROM labelled CROSS JOIN port GROUP BY segment ORDER BY vs_port
    """)

    fig, ax = plt.subplots(figsize=(10.4, 5.8))
    y = np.arange(len(df))
    # three states, because "below average" and "loses money" are different things
    colors = [
        CRITICAL if ny < 0 else (ORANGE if v < 0 else BLUE)
        for v, ny in zip(df.vs_port, df.net_yield)
    ]
    ax.barh(y, df.vs_port, color=colors, height=0.62, zorder=3)
    ax.axvline(0, color=INK, lw=1.2, zorder=4)

    for yi, (v, ny) in enumerate(zip(df.vs_port, df.net_yield)):
        off = 0.28 if v >= 0 else -0.28
        ax.text(v + off, yi, f"{ny:+.2f}%",
                va="center", ha="left" if v >= 0 else "right",
                fontsize=9, color=INK_2)

    ax.set_yticks(y)
    ax.set_yticklabels([f"{s}  ({n:,})" for s, n in zip(df.segment, df.loans)],
                       fontsize=9.5)
    ax.set_xlabel("Risk-adjusted net yield vs portfolio average"
                  "   (labels show the segment's own net yield)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.0f}pp"))
    ax.set_xticks([-15, -12, -9, -6, -3, 0, 3, 6, 9])
    ax.set_xlim(-16.5, 10.5)
    ax.grid(axis="x", zorder=0)
    ax.set_axisbelow(True)

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=BLUE),
        plt.Rectangle((0, 0), 1, 1, color=ORANGE),
        plt.Rectangle((0, 0), 1, 1, color=CRITICAL),
    ]
    ax.legend(handles, ["Beats the portfolio", "Below the portfolio, still profitable",
                        "Loses money"],
              frameon=False, fontsize=9, loc="lower right", bbox_to_anchor=(1.0, 0.01))

    fig.suptitle("Where the book makes and loses money, after funding, servicing and loss",
                 fontsize=13, fontweight="bold", x=0.009, ha="left", y=1.0)
    fig.text(0.009, 0.945,
             "Portfolio baseline 4.81%. Grade E impairs 6.6x more than grade A and is "
             "still the better asset — the risk is priced.",
             fontsize=9.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0.02, 1, 0.92])
    finish(fig, "04_segment_league_table.png",
           "net yield = coupon - 3.0% funding - 1.0% servicing - annualised expected loss.")


# ---------------------------------------------------------------------------
# 5. What the overlay is worth — a waterfall.
# ---------------------------------------------------------------------------
def chart_impact_waterfall():
    steps = [
        ("Current\nbook", 4.81, "base"),
        ("Decline\nTier 1", 0.80, "up"),
        ("Reprice\nTier 2", 0.58, "up"),
        ("After\noverlay", 6.19, "total"),
    ]
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    running = 0.0
    for i, (label, val, kind) in enumerate(steps):
        if kind == "base":
            ax.bar(i, val, width=0.58, color=BLUE, zorder=3)
            ax.text(i, val + 0.12, f"{val:.2f}%", ha="center", fontsize=10.5,
                    fontweight="bold", color=INK)
            running = val
        elif kind == "up":
            ax.bar(i, val, bottom=running, width=0.58, color=GOOD, zorder=3)
            ax.plot([i - 0.29, i - 0.29], [running, running], color=AXIS, lw=1)
            ax.hlines(running, i - 0.79, i - 0.29, color=AXIS, lw=1, linestyles=":")
            ax.text(i, running + val + 0.12, f"+{val*100:.0f}bps",
                    ha="center", fontsize=10.5, fontweight="bold", color=GOOD)
            running += val
        else:
            ax.bar(i, val, width=0.58, color=BLUE, zorder=3)
            ax.hlines(running, i - 0.79, i - 0.29, color=AXIS, lw=1, linestyles=":")
            ax.text(i, val + 0.12, f"{val:.2f}%", ha="center", fontsize=10.5,
                    fontweight="bold", color=INK)

    ax.set_xticks(range(len(steps)))
    ax.set_xticklabels([s[0] for s in steps])
    ax.set_ylabel("Risk-adjusted net yield")
    ax.yaxis.set_major_formatter(PCT)
    ax.set_ylim(0, 7.4)
    ax.grid(axis="y", zorder=0)
    ax.set_axisbelow(True)

    fig.suptitle("The overlay is worth 138bps of net yield",
                 fontsize=13, fontweight="bold", x=0.009, ha="left", y=1.0)
    fig.text(0.009, 0.94,
             r"\$2.0M a year on this \$144.6M book; \$6.9M on a \$500M origination programme.",
             fontsize=9.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0.02, 1, 0.92])
    finish(fig, "05_impact_waterfall.png",
           "Scenario B: decline Tier 1, reprice Tier 2 +400bps at 35% assumed attrition, "
           "capital redeployed at the Core net yield.")


# ---------------------------------------------------------------------------
# 6. Does the conclusion survive the assumptions?
# ---------------------------------------------------------------------------
def chart_sensitivity():
    path = ROOT / "outputs" / "tables" / "sensitivity_roll_rates.csv"
    if not path.exists():
        print("  skipping sensitivity chart — run python/04_sensitivity.py first")
        return
    df = pd.read_csv(path)

    fig, ax = plt.subplots(figsize=(8.8, 4.2))
    x = np.arange(len(df))
    series = [
        ("Core (grow)", "CORE_net_yield_pct", BLUE, "o"),
        ("Tier 2 (reprice)", "T2_REPRICE_net_yield_pct", ORANGE, "s"),
        ("Tier 1 (decline)", "T1_DECLINE_net_yield_pct", CRITICAL, "D"),
    ]
    for label, col, color, marker in series:
        ax.plot(x, df[col], color=color, lw=2, marker=marker, markersize=8,
                markeredgecolor=SURFACE, markeredgewidth=1.6, label=label, zorder=3)
        ax.text(x[-1] + 0.09, df[col].iloc[-1], f"  {label}",
                va="center", fontsize=9.5, color=INK_2)

    ax.axhline(0, color=AXIS, lw=1.1, zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace(" ", "\n") for s in df.roll_scenario])
    ax.set_xlabel("Roll-to-charge-off assumption")
    ax.set_ylabel("Risk-adjusted net yield")
    ax.yaxis.set_major_formatter(PCT)
    ax.set_xlim(-0.25, len(df) - 0.25 + 1.5)
    ax.set_ylim(-1.5, 7.5)
    ax.grid(axis="y", zorder=0)
    ax.set_axisbelow(True)

    fig.suptitle("The ranking does not depend on the assumptions",
                 fontsize=13, fontweight="bold", x=0.009, ha="left", y=1.06)
    fig.text(0.009, 0.975,
             "Loss levels move with the roll rates; the order of the three tiers is "
             "identical in all 16 scenarios tested.",
             fontsize=9.5, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0.02, 1, 0.92])
    finish(fig, "06_sensitivity.png",
           "Roll rates flexed from optimistic (15/30/55%) to very severe (60/75/95%).")


def main() -> None:
    print("Rendering charts ...")
    chart_risk_vs_price()
    chart_verification()
    chart_purpose_quadrant()
    chart_segment_league()
    chart_impact_waterfall()
    chart_sensitivity()
    print(f"\nCharts in {CHARTS.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
