# Data

## Provenance

| | |
|---|---|
| **Dataset** | `loans_full_schema` |
| **Publisher** | OpenIntro (R package `openintro`) |
| **Original source** | LendingClub loan-level origination disclosures |
| **Mirror used** | [Rdatasets](https://github.com/vincentarelbundock/Rdatasets) |
| **Direct URL** | `https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/openintro/loans_full_schema.csv` |
| **Rows** | 10,000 |
| **Columns** | 55 (+ row index) |
| **Vintage** | Loans issued January–March 2018 |
| **Licence** | Publicly released loan-level data; OpenIntro distributes it for educational use |

This is **real lending data**. No rows are simulated, imputed or synthesised anywhere in this repository.

To re-download:

```bash
curl -o data/raw/loans_full_schema.csv \
  https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/openintro/loans_full_schema.csv
```

## Observation window

Loans were issued across three consecutive months and observed at a single later date, so cohorts differ in seasoning:

| Issue month | Loans | Avg payments made | Early impairment |
|---|---|---|---|
| Jan 2018 | 3,395 | 6.7 | 2.33% |
| Feb 2018 | 2,988 | 5.5 | 1.67% |
| Mar 2018 | 3,617 | 4.0 | 1.35% |

Impairment rises with seasoning, as it must. Normalised per payment opportunity the three cohorts are close (0.346 / 0.305 / 0.343), so the vintages are treated as one pool. `sql/01_portfolio_overview.sql` Q3 runs this check.

## Fields used

### Outcome
| Field | Notes |
|---|---|
| `loan_status` | Current, Fully Paid, In Grace Period, Late (16-30), Late (31-120), Charged Off |
| `balance` | Outstanding principal |
| `paid_total`, `paid_principal`, `paid_interest` | Cash received to date |

### Loan terms
| Field | Notes |
|---|---|
| `loan_amount`, `term`, `interest_rate`, `installment` | Contract terms at origination |
| `grade`, `sub_grade` | LendingClub's own risk grade — the incumbent pricing dimension |
| `loan_purpose` | Borrower-stated purpose, 12 levels |
| `application_type` | individual / joint |
| `issue_month` | Origination month |

### Borrower attributes at application
| Field | Notes |
|---|---|
| `annual_income`, `verified_income` | Income and whether LendingClub verified it (Not Verified / Source Verified / Verified) |
| `debt_to_income` | Reported up to 469%; values >100% flagged, not dropped |
| `homeownership` | RENT / MORTGAGE / OWN (outright) |
| `emp_length`, `emp_title` | Employment |
| `total_credit_limit`, `total_credit_utilized`, `total_debit_limit` | Bureau balances |
| `delinq_2y`, `inquiries_last_12m`, `accounts_opened_24m` | Recent credit behaviour |
| `public_record_bankrupt`, `tax_liens`, `num_collections_last_12m` | Derogatory marks |
| `earliest_credit_line`, `account_never_delinq_percent` | File depth and history quality |

## Cleaning rules

Applied in `python/01_build_db.py`. Each is deliberate and reversible; the untouched source is preserved in the `raw_loans` table.

| Rule | Reason |
|---|---|
| `annual_income = 0` → NULL (23 rows) | Zero income is not a real value and breaks every ratio using it as a denominator. Nulled rather than dropped so the loan still counts in volume metrics. |
| `debt_to_income > 100` → flagged via `dti_implausible`, retained | Usually a joint-application artefact. Excluding them would bias the DTI analysis toward the conclusion being tested. |
| `issue_month` → `issue_date` | Enables cohort ordering. |

### Missingness

| Field | Missing | Handling |
|---|---|---|
| `annual_income_joint`, `debt_to_income_joint` | 85.0% | Structural — only populated for joint applications |
| `months_since_90d_late` | 77.1% | Structural — only populated if the borrower has been 90d late |
| `months_since_last_delinq` | 56.6% | Structural — absence *is* the signal |
| `emp_title` / `emp_length` | 8.3% / 8.2% | Left null; not used in any conclusion |
| `debt_to_income` | 0.2% | Excluded from DTI quintiles only |

Structural missingness is never imputed. A null in `months_since_last_delinq` means "never delinquent", and filling it with a median would destroy exactly the information the field carries.

## Derived fields

| Field | Definition |
|---|---|
| `is_impaired` | `loan_status` in (In Grace Period, Late 16-30, Late 31-120, Charged Off) |
| `is_serious` | `loan_status` in (Late 31-120, Charged Off) |
| `payments_made` | `paid_total / installment` — seasoning proxy |
| `credit_utilization` | `total_credit_utilized / total_credit_limit` |
| `payment_to_income` | `installment × 12 / annual_income` |
| `credit_history_years` | `issue year − earliest_credit_line` |
| `income_verified_flag` | `verified_income = 'Verified'` |
| `is_prime` | `grade in ('A','B')` |
| `elevated_purpose_flag` | `loan_purpose in (house, medical, major_purchase, car, moving)` |
| `joint_flag`, `outright_owner_flag` | Application type and homeownership flags |
| `roll_to_co`, `ew_loss_usd`, `annual_loss_usd`, `net_margin_usd` | Credit economics — see README §4 |
