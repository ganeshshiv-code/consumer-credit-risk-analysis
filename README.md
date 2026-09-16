# Finding Risk That Nobody Charged For: A $163M Loan Book

I analysed 10,000 real LendingClub personal loans and found about $2 million a year in risk that wasn't being properly priced.

**Tools:** SQL (DuckDB) · Python (pandas, scipy, statsmodels) · HTML/JS dashboard
**[Live dashboard](dashboard/index.html)** · **[Full write-up](CASE_STUDY.md)**

---

## The problem

A lender gave out $163.6M in personal loans in early 2018. Four months later, 1.78% had already missed a payment. That is a normal number, so nothing looked wrong.

But I wanted to know *which* loans were going bad, and whether the interest charged on those loans was enough to cover the losses.

## What I found

The lender's credit grade works fine. Grade A loans go bad 0.77% of the time, grade E loans 5.07%, and the interest rate rises faster than the risk does.

The problem is three things the grade never looks at:

| What it is | How much worse | What the lender charges for it |
|---|---|---|
| Income was verified, in the top grades | **5.4x** more missed payments (p=0.0006) | 0.13% more. Basically nothing |
| Loan is for a house, medical bill, car or big purchase | **2.4x** more (p=0.00004) | 0.46% **less** than average |
| Borrower owns their home outright, no mortgage | **1.5x** more (p=0.035) | Nothing extra |

When a loan has two or more of these, it goes bad 4.00% of the time instead of 1.48%, and gets charged a *lower* rate.

![Risk rises while price falls](outputs/charts/01_risk_vs_price.png)

**27.5% of the loans cause 44.1% of the losses.**

## What I recommended

| | Loans | Profit margin | Action |
|---|---|---|---|
| Group 1 | 1,026 | −0.18% | Stop lending. These cost more than they earn |
| Group 2 | 1,720 | +2.51% | Charge 4% more. Profitable, but underpriced for the risk |
| Group 3 | 7,254 | +6.16% | Lend more. Best returns in the book |

Doing this takes the overall profit margin from **4.81% to 6.19%**. That is **$2.0M a year** on this book, or **$6.9M** if the lender writes $500M a year.

I re-ran the whole thing under 16 different sets of assumptions. The ranking of the three groups was the same in all 16.

## What I got wrong

I wrote down six things I expected to find before I started. Four were wrong, and two of those were the most useful results in the project:

- **Debt-to-income points the wrong way.** The borrowers with the *least* debt missed the most payments (2.51% vs 1.20% in the middle). Tightening that check would have made this book worse.
- **Joint applications really are riskier** (1.5x, p=0.033), but they are already charged enough to cover it. So I recommended doing nothing. Statistically significant is not the same as worth acting on.

## How to run it

```bash
pip install -r requirements.txt
python python/01_build_db.py          # load and clean the CSV
python python/02_run_sql.py           # run every SQL file
python python/03_statistical_tests.py # significance tests and regression
python python/04_sensitivity.py       # the 16 stress tests
python python/05_charts.py            # the charts
```

| Folder | What is in it |
|---|---|
| `sql/` | The analysis: segments, confidence ranges, profit margins, the decision rules |
| `python/` | Loading, statistics, stress tests, charts, dashboard build |
| `dashboard/` | Single-file interactive dashboard with a live scenario model |
| `data/` | The raw CSV and a [full data dictionary](data/README.md) |
| `outputs/` | 6 charts and 21 result tables |

Every number here is generated from the raw data by running the analysis scripts.

**Data:** Real LendingClub records, [published by OpenIntro](https://www.openintro.org/data/index.php?data=loans_full_schema), mirrored on [Rdatasets](https://github.com/vincentarelbundock/Rdatasets). Nothing simulated.

**The honest limits:** the loans are only 4 months old, I only see approved applicants, and my biggest purpose finding rests on 151 loans. All four limitations are written up properly in the [full version](CASE_STUDY.md).
