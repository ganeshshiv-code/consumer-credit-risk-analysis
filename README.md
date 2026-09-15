# Uncompensated Risk in a $163M Consumer Loan Book

**A credit-risk analysis of 10,000 real LendingClub personal loans — finding 138bps of net yield the pricing engine was giving away.**

---

## Executive summary

A $163.6M unsecured personal-loan vintage was underwritten in Q1 2018. Four months in, 1.78% of accounts have already missed a payment. That number is unremarkable on its own. What it hides is *where* the misses sit.

The credit grade works: impairment rises monotonically from 0.77% at grade A to 5.07% at grade E, and the coupon rises faster, so the riskiest grades are the **most** profitable assets in the book. The problem is elsewhere. Three borrower attributes that the grade does not capture — **income-verification status in prime grades, loan purpose, and outright home ownership** — carry statistically significant risk that is priced at, or below, the book average.

The effect compounds. Loans carrying two or more of these attributes impair at **4.00%** versus **1.48%** for unflagged loans, while their average coupon *falls* from 13.13% to 10.09%.

![Risk rises while price falls](outputs/charts/01_risk_vs_price.png)

**27.5% of accounts carry 44.1% of the modelled loss.** Declining the two segments that fail to cover their own cost of capital, and repricing the rest, lifts risk-adjusted net yield from **4.81% to 6.19% — +138bps, worth $2.0M a year on this book and $6.9M on a $500M origination programme.**

The tier ranking that drives that recommendation held in all 16 assumption scenarios tested.

---

## 1. Business problem

> *"Our grade-level loss rates are within tolerance and our pricing model is performing as designed. So why is blended net yield running below plan?"*

This is the question a portfolio analyst actually gets asked, and the two halves of it are both true at once. A risk-based pricing engine can be working perfectly *within* its own dimensions and still lose money, because it can only price what it measures.

The analysis therefore does not ask "is the grade wrong?" It asks a narrower, more useful question:

**Which borrower attributes predict early default but do not move the price?**

Anything in that set is risk the book is carrying for free. The deliverable is a list of those attributes, the money attached to each, and an underwriting overlay the credit committee can approve on one page.

**Scope note.** The data is real; the institutional framing is an analytical exercise. I take the position of an analyst at the firm holding this book, because a credit finding is only worth something when it is expressed as a decision and a dollar amount.

---

## 2. Hypotheses

Stated and pre-registered before the analysis, so that rejections count as results rather than as dead ends. Four of the six failed, and two of the failures were more informative than the successes.

| # | Hypothesis | Prior reasoning | Result |
|---|---|---|---|
| **H1** | Income verification reduces risk | Verified income is better information, so verified loans should perform better | **Rejected, and reversed** — verified loans impair **2.96x** more in prime grades (p=0.0004) and show no effect below (p=1.00) |
| **H2** | Loan purpose carries risk the price ignores | Purpose proxies for financial pressure; the pricing engine barely uses it | **Confirmed** — elevated-purpose loans impair 2.37x more (p=0.00004) at a coupon 46bps *below* the book |
| **H3** | Higher debt-to-income means higher risk | The standard affordability metric | **Rejected, inverted** — the *lowest* DTI quintile impairs most (2.51%); DTI odds ratio 0.98, p=0.0019 |
| **H4** | 60-month loans are riskier than 36-month | Longer exposure, weaker borrowers | **Rejected as a mix effect** — significant alone (p=0.011), vanishes once grade is controlled (OR 0.90, p=0.53). The grade already prices it |
| **H5** | Outright home ownership is a strength | No mortgage means lower fixed obligations | **Rejected, reversed** — outright owners impair 1.51x more than mortgage holders (p=0.035; OR 1.55 multivariate) |
| **H6** | Joint applications reduce risk | Two incomes supporting one loan | **Rejected statistically, but no action taken** — joint loans impair 1.49x more (p=0.033), yet earn +5.72% net yield. Significant ≠ actionable |

H6 is the discipline point of the project. A significant risk finding that is already adequately priced is not a problem to fix. Three of the six hypotheses produced real findings; the rest are reported as failures rather than quietly dropped.

---

## 3. Data

**Source:** LendingClub loan-level originations, published as `loans_full_schema` in the [openintro](https://www.openintro.org/data/index.php?data=loans_full_schema) R package, mirrored in [Rdatasets](https://github.com/vincentarelbundock/Rdatasets).

This is **real lending data**, not a simulation: 10,000 loans issued January–March 2018, 55 fields covering borrower credit bureau attributes at application, loan terms, and repayment status at the observation date.

| | |
|---|---|
| Loans | 10,000 |
| Originated | $163.6M |
| Outstanding | $144.6M |
| Vintage | Jan–Mar 2018 |
| Seasoning at observation | ~4–5 scheduled payments |
| Weighted-average coupon | 12.66% |
| Grade mix | A 24.6% · B 30.4% · C 26.5% · D 14.5% · E–G 4.1% |

### Outcome definition

The book is four months old, so ultimate default is unobservable. The analysable outcome is **early impairment** — any loan that has already missed a payment:

```
impaired = loan_status IN ('In Grace Period', 'Late (16-30 days)',
                           'Late (31-120 days)', 'Charged Off')
```

178 loans (1.78%), $3.00M of principal (2.07%).

Early-stage delinquency is the standard early-warning metric for a fresh vintage precisely because waiting for charge-offs means waiting two years to learn something you needed at origination.

### Honest limitations

A portfolio project that hides its weaknesses is not worth reading. This one has four:

1. **Short seasoning.** Four months of performance predicts the *ranking* of segments well and the *level* of lifetime loss poorly. Every absolute loss number here is scaled by an assumption (§7), and the recommendation is built to survive that (§7.3).
2. **Survivorship in the platform's own funnel.** These are funded loans. Applicants LendingClub declined are invisible, so every effect measured is conditional on having passed their underwriting.
3. **Small segments.** `house` purpose is 151 loans and 10 impairments. Every rate in this repo carries a Wilson 95% interval for that reason, and no recommendation rests on a segment whose interval crosses the portfolio average.
4. **One vintage, one macro environment.** Q1 2018 was a benign credit period. The *direction* of these effects should replicate; the magnitudes would need a multi-vintage test.

---

## 4. Method

Two layers, deliberately separated.

**SQL (DuckDB)** does the portfolio arithmetic — segmentation, roll rates, the economics, the decision tiers. Every business number in this README traces to a query in `sql/`. Wilson confidence intervals are implemented as SQL macros so that no rate is ever reported bare.

**Python** does the things SQL should not: significance testing, multivariate control, sensitivity analysis, and chart export.

```bash
pip install -r requirements.txt

python python/01_build_db.py         # CSV -> DuckDB, cleaning + features
python python/02_run_sql.py          # run every sql/ file, print + save results
python python/03_statistical_tests.py # Fisher exact, logistic regression, interaction
python python/04_sensitivity.py       # do the conclusions survive the assumptions?
python python/05_charts.py            # export figures
```

### The economics

A segment is only a problem if it fails to cover what it costs to hold:

```
net yield = coupon − cost of funds − servicing − annualised expected loss
```

| Assumption | Value | Basis |
|---|---|---|
| Roll to charge-off — grace / 16-30 / 31-120 dpd | 30% / 45% / 70% | Industry convention, unsecured consumer instalment |
| Loss given default | 85% | Unsecured, ~15% recovery |
| Cost of funds | 3.0% | 2018 rate environment |
| Servicing + platform | 1.0% | Marketplace investor fee |
| Lifetime charge-off anchor | 9.0% | Used to season a 4-month book |

The seasoning anchor deserves a flag. It converts observed early impairment into a lifetime loss estimate through a **single portfolio-level scalar (k = 8.81)**. Because the same scalar multiplies every loan, it sets the absolute level of loss and never the ranking between segments — which is the only property the recommendation depends on. §7.3 demonstrates this rather than asserting it.

---

## 5. Findings

### Finding 1 — Income verification means the opposite thing in prime and subprime

![The verification paradox](outputs/charts/02_verification_paradox.png)

Within grade A, income-verified borrowers impair at **2.56%** against **0.47%** for everyone else — **5.4x the risk**, Fisher exact p=0.0006. They pay **13bps** more for it.

The effect is confined to the top of the book. In grades C and D it disappears entirely, and in D it reverses. Tested formally, the verification × credit-band interaction has an **odds ratio of 3.3 (p=0.0007)**, while verification as a standalone main effect is not significant (p=0.13) — the two opposing effects cancel out when averaged.

**The mechanism matters more than the coefficient.** Verification is not randomly assigned; the platform chooses whom to verify. In the prime band, being asked to document income is a signal that something in the application did not reconcile on its own — variable compensation, self-employment, thin documentation. The verification *outcome* is clean, which is why the loan is graded A. The verification *trigger* is the information, and the grade never sees it.

Below prime, applicants are being verified as a matter of course, so the trigger carries no signal — exactly what the data shows.

A grade-A loan at a 5.31% coupon in this book is already 31–120 days late. That is a loan the pricing engine believed was among the safest assets it had.

### Finding 2 — Loan purpose is risk information sitting unused

![Purpose risk against price](outputs/charts/03_purpose_quadrant.png)

Every purpose below the horizontal line is priced under the book average. Several of them sit well to the right of it.

| Purpose | Loans | Impairment | 95% CI | vs book | Coupon vs book |
|---|---|---|---|---|---|
| house | 151 | **6.62%** | 3.64–11.76% | 3.7x | **−1.29pp** |
| medical | 162 | 3.70% | 1.71–7.84% | 2.1x | −0.51pp |
| car | 131 | 3.05% | 1.19–7.59% | 1.7x | −0.62pp |
| major purchase | 303 | 2.97% | 1.57–5.55% | 1.7x | −0.69pp |
| credit card | 2,249 | 1.07% | 0.72–1.58% | 0.6x | −1.23pp |

Pooled into a single **elevated-purpose** set (house, medical, car, major purchase, moving — 816 loans), impairment is **3.80% vs 1.60%**, p=0.00004, and the effect survives multivariate control at **odds ratio 2.39 (p<0.0001)** — the strongest non-grade driver in the model.

`credit_card` is the mirror image and equally useful: 0.6x the risk, and it is *also* priced below the book. Refinancing a revolving balance into a fixed instalment is a deleveraging act by a borrower who is managing their position. That segment should be grown, not just left alone.

`home_improvement` (2.21%, CI 1.34–3.61%) sits close enough to the book average that its interval overlaps. It goes on the watchlist, not in the overlay.

### Finding 3 — Debt-to-income is pointing the wrong way

| DTI quintile | Range | Loans | Impairment | 95% CI |
|---|---|---|---|---|
| 1 | 0.0–9.7% | 1,996 | **2.51%** | 1.91–3.29% |
| 2 | 9.7–15.1% | 1,995 | 1.30% | 0.89–1.90% |
| 3 | 15.1–20.3% | 1,995 | 1.20% | 0.81–1.78% |
| 4 | 20.3–27.0% | 1,995 | 1.95% | 1.43–2.66% |
| 5 | 27.0–469% | 1,995 | 1.90% | 1.39–2.60% |

The lowest-DTI quintile — the borrowers an affordability screen would rank safest — impairs at twice the rate of the middle. Multivariate, DTI's odds ratio is **0.98 per point, p=0.0019**: significant, and pointing the wrong way.

The likely reading is that low measured DTI in this population is not financial strength but a **thin credit file**. A borrower with little existing debt has little repayment history to have been graded on. The U-shape is what a screen would look like if it were conflating "no obligations" with "proven ability to meet obligations."

This does not become a recommendation — it becomes a warning against the intuitive one. Any proposal to tighten the DTI cap would have made this book worse.

### Finding 4 — The grade is working; do not touch it

![Segment league table](outputs/charts/04_segment_league_table.png)

| Grade | Loans | Impairment | Coupon | Annual loss | Net yield |
|---|---|---|---|---|---|
| A | 2,459 | 0.77% | 6.69% | 1.70% | **+0.99%** |
| B | 3,037 | 1.09% | 10.52% | 2.16% | +4.36% |
| C | 2,653 | 1.96% | 14.15% | 3.93% | +6.23% |
| D | 1,446 | 3.39% | 19.16% | 7.42% | +7.74% |
| E | 335 | 5.07% | 25.23% | 10.15% | **+11.07%** |

Grade E impairs **6.6x** more than grade A and earns **11 times the net yield**. Read the impairment column alone and you would cut exactly the wrong end of the book.

Grade A is the weakest asset the portfolio holds, at +0.99%, because a 6.69% coupon leaves 269bps to absorb funding, servicing and loss. It has almost no margin for an underwriting error — which is what makes Finding 1 expensive rather than merely interesting.

*(Grades F and G, at 58 and 12 loans, are too small to read. They are excluded from every conclusion here.)*

### Finding 5 — The flags compound

| Uncompensated-risk flags | Loans | % of balance | Impairment | Coupon | % of modelled loss | Concentration |
|---|---|---|---|---|---|---|
| None | 7,254 | 72.4% | 1.48% | 12.79% | 55.9% | 0.77 |
| One | 2,446 | 24.6% | 2.41% | 11.64% | 37.0% | **1.51** |
| Two or more | 300 | 3.1% | 4.00% | 10.04% | 7.1% | **2.31** |

Risk climbs, price falls, and loss concentration triples. The flags are not redundant with each other, and none of them is in the price.

---

## 6. Recommendations

Three tiers, each with an owner and a decision, not an observation.

### Tier 1 — Decline (1,026 loans · $18.3M · net yield −0.18%)

**Rule:** `loan_purpose = 'house'` **OR** (`grade IN ('A','B')` **AND** `income_verified = 'Verified'`)

These segments do not cover their own cost of capital. The book pays to own them.

*Caveat, stated plainly:* Tier 1 is negative under the base assumptions and in 8 of 12 single-assumption stress scenarios. Under the most benign set (LGD 70%, funding 2.0%) it turns marginally positive at +0.8%. It is the worst tier in **every** scenario tested; it is a *loss-making* tier in most of them. If the credit committee prefers the softer action, Tier 1 reprices at +600bps instead of declining — the pricing math is in `sql/04_decision_framework.sql`.

### Tier 2 — Reprice +400bps (1,720 loans · $21.6M · net yield +2.51%)

**Rule:** remaining elevated-purpose loans (medical, car, major purchase, moving) **OR** `homeownership = 'OWN'`

Profitable, but earning 365bps less than Core for more risk. Price the risk rather than refusing it.

### Core — Grow (7,254 loans · $104.6M · net yield +6.16%)

Actively expand `credit_card` refinance, mortgage-holding borrowers, and grades C–E, which are the highest risk-adjusted returns in the book. Leave joint applications alone: riskier, but already paid for.

### Process changes

1. **Add loan purpose and verification-trigger status to the pricing model as rated factors.** They are collected at application and currently discarded. This is the finding with the longest shelf life — the segments will drift, the fact that the model is blind to them will not.
2. **Log *why* verification was triggered, not just its outcome.** Finding 1 says the trigger carries the signal. Nobody is currently capturing it.
3. **Stop treating low DTI as a strength in isolation.** Pair it with credit-file depth before it earns a pricing benefit.
4. **Report the monthly uncompensated-risk watchlist** (`sql/04_decision_framework.sql`, Q4) to the credit committee.

---

## 7. Measurable business impact

### 7.1 The scenarios

| | Net yield | Uplift | On this $144.6M book | On $500M originations |
|---|---|---|---|---|
| Current | 4.81% | — | — | — |
| **A** — decline Tier 1, redeploy to Core | 5.61% | **+80bps** | +$1.16M | +$4.02M |
| **B** — A, plus reprice Tier 2 +400bps | **6.19%** | **+138bps** | **+$2.00M** | **+$6.92M** |

![Impact waterfall](outputs/charts/05_impact_waterfall.png)

### 7.2 The one behavioural assumption

Scenario B assumes 35% of repriced Tier 2 borrowers leave for a cheaper lender. That is a guess, so it was flexed across its entire possible range:

| Attrition | 0% | 20% | 35% | 50% | 70% | 100% |
|---|---|---|---|---|---|---|
| Uplift | +140bps | +139bps | **+138bps** | +138bps | +136bps | +135bps |

The recommendation is insensitive to it. Even if *every* repriced borrower walks, the uplift is +135bps, because the capital redeploys into Core at +6.16%.

### 7.3 Does the conclusion survive the assumptions?

![Sensitivity](outputs/charts/06_sensitivity.png)

Roll rates flexed from optimistic (15/30/55%) to very severe (60/75/95%), plus LGD, funding, servicing and the lifetime anchor moved one at a time.

**The tier ranking — Core > Tier 2 > Tier 1 — held in all 16 scenarios.** Loss *levels* move with the assumptions, as they should. The *ordering* that the recommendation depends on does not.

### 7.4 How to know whether it worked

A number in a deck is not an impact. The measurement plan:

| Horizon | Metric | Target |
|---|---|---|
| Month 1 | Applications flagged by the overlay | ~27% of volume, matching backtest |
| Month 3 | Tier 2 acceptance rate after repricing | ≥65% (the 35% attrition assumption) |
| Month 6 | Early impairment, new vintage vs Q1-2018 | 1.78% → ≤1.35% |
| Month 12 | Blended net yield | 4.81% → ≥5.90% |
| Month 12 | Overlay-declined applications funded by competitors | Tracked — the false-positive check |

**Run it as a champion/challenger, not a switch.** Hold out 10% of qualifying applications from the overlay for twelve months. Without a control group, a benign macro quarter will take credit for the analyst's work and an adverse one will take the blame.

---

## 8. What I would do next

- **Multi-vintage replication.** One vintage in a benign quarter is one observation. The verification interaction is the specific claim I would most want to see hold in 2019 and 2020 books.
- **Get the verification trigger.** Finding 1 infers the mechanism from the outcome. The trigger reason would test it directly, and it is a field the platform already has.
- **Competing-risk treatment of prepayment.** 447 loans were fully repaid within four months. Early prepayment removes good credits from the denominator and is being ignored here.
- **A scorecard, once the seasoning supports one.** At 178 events, a model would fit the noise. At 24 months and ~900 events, a proper scorecard with out-of-time validation becomes defensible. Deciding *not* to model yet is part of the analysis.

---

## Repository

```
credit-risk-analysis/
├── README.md                      # this case study
├── requirements.txt
├── data/
│   ├── raw/loans_full_schema.csv  # real LendingClub Q1-2018 originations
│   └── README.md                  # provenance and data dictionary
├── sql/
│   ├── 01_portfolio_overview.sql  # baseline, delinquency waterfall, grade check
│   ├── 02_hypothesis_tests.sql    # H1-H5 with Wilson intervals (SQL macros)
│   ├── 03_segment_economics.sql   # net yield by segment, loss concentration
│   └── 04_decision_framework.sql  # decision tiers, scenario model, watchlist
├── python/
│   ├── 01_build_db.py             # load, clean, engineer, document assumptions
│   ├── 02_run_sql.py              # SQL runner -> console + CSV
│   ├── 03_statistical_tests.py    # Fisher exact, logistic regression, interaction
│   ├── 04_sensitivity.py          # assumption stress tests
│   └── 05_charts.py               # figure export
├── dashboard/index.html           # single-page interactive dashboard
└── outputs/
    ├── charts/                    # figures used above
    └── tables/                    # every query result as CSV
```

**Stack:** Python (pandas, DuckDB, statsmodels, scipy, matplotlib) · SQL (DuckDB) · HTML/CSS/JS dashboard

### Reproduce everything

```bash
pip install -r requirements.txt
python python/01_build_db.py          # CSV -> DuckDB
python python/02_run_sql.py           # every SQL file -> console + outputs/tables/
python python/03_statistical_tests.py # Fisher exact, logistic regression, interaction
python python/04_sensitivity.py       # 16 assumption scenarios
python python/05_charts.py            # outputs/charts/*.png
python python/06_dashboard_data.py    # database -> dashboard/data.json
python python/07_build_dashboard.py   # -> dashboard/index.html (self-contained)
```

Every number in this README and on the dashboard is produced by that pipeline.
Nothing is typed in by hand, so a change to an assumption in
`python/01_build_db.py` propagates to all of it.

---

## Interactive dashboard

`dashboard/index.html` is a single self-contained file — open it directly in a
browser, no server required.

- **Live scenario model.** Move the Tier 2 attrition and repricing-premium sliders
  and the waterfall, the uplift and the headline recommendation all recompute from
  the tier balances in the database.
- **Metric toggle** on the segment league table, so you can see why impairment rate
  alone would cut the wrong end of the book.
- **Sortable hypothesis register**, including the tests that failed.
- **Monthly watchlist** — every impaired loan carrying an uncompensated-risk flag.
- Wilson intervals on every rate, hover detail on every mark, and a dark mode.

It is a rendering layer only: `python/06_dashboard_data.py` exports the figures
from DuckDB and `python/07_build_dashboard.py` inlines them, so the dashboard can
never disagree with the analysis.

---

## Sources

- [LendingClub `loans_full_schema`](https://www.openintro.org/data/index.php?data=loans_full_schema) — OpenIntro
- [Rdatasets mirror](https://github.com/vincentarelbundock/Rdatasets/blob/master/csv/openintro/loans_full_schema.csv) — direct CSV
