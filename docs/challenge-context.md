# HackSpain 2026 — Embat X-Ray Challenge Context

## 1. Challenge

**HackSpain 2026 · X-Ray · Embat**

### Core question

> Can money tell us how a company is doing?

We are given the financial trail of companies over 24 months.

Our goal is to build:

**Financial Data → Financial Health Score → Sellable Product**

The **score is the engine, not the final product**.

The solution must understand not only the current financial state of a company, but also its **trajectory**:

- Is the company financially healthy?
- Is it improving?
- Is it deteriorating?
- Is a bad month temporary or structural?
- Why has its financial health changed?
- How early could we detect that change?

---

# 2. Dataset

The dataset contains:

- **250 business groups**
- **1,286 synthetic companies**
- **24 months of financial history**
- September 2024 → September 2026
- Hidden test set of approximately **60–80 companies**

The data is synthetic but generated from statistical distributions of real SME treasury data.

## Available data

### `groups.csv`
Business groups / holdings.

### `companies.csv`
Company metadata:
- group
- country
- currency
- ERP
- onboarding date

`company_id` is the main key across datasets.

### `banking_products.csv`
Banking products:
- current accounts
- cards
- POS
- savings
- investments
- expense platforms

### `debt_products.csv`
Financing products:
- loans
- leasing
- credit lines
- mortgages
- renting
- factoring
- confirming
- guarantees

Includes granted amount and outstanding balance.

### `debt_schedule_config.csv`
Debt repayment conditions:
- installment type
- payment frequency
- number of installments
- interest rate
- next payment date

### `transactions.csv`
Bank transactions:
- date
- amount
- category
- reconciliation status
- counterparty
- bank concept

### `invoices.csv`
ERP invoices, both issued and received:
- issue date
- due date
- collection/payment date
- outstanding amount
- status
- counterparty

### `balances.csv`
Final account/product balances as of September 1, 2026.

### `data_dictionary.md`
Definition of all dataset fields.

---

# 3. Core Problem

Traditional financial analysis often looks at snapshots.

This challenge wants us to understand **financial behavior over time**.

Example:

Company A:

    45 → 52 → 58 → 65

Company B:

    82 → 78 → 73 → 68

Their current scores may be similar, but their trajectories are completely different.

Company A is improving.

Company B is deteriorating.

Therefore:

> Financial health is not only where a company is today.
> It is where it came from and where it appears to be going.

---

# 4. Financial Health Score

The core technical component is a:

# Financial Health Score

Potential range:

    0 ─────────────────────────── 100
    Critical                     Excellent

The score must capture:

- current financial health
- historical trajectory
- improvement
- deterioration
- persistence of changes
- temporary vs structural movements

The score must generalize to companies that the system has never seen.

---

# 5. Potential Financial Signals

Potential features/signals include:

## Liquidity

- Cash balance
- Cash buffer
- Cash burn
- Cash-flow trend
- Cash-flow volatility
- Inflows vs outflows

## Revenue / inflows

- Inflow trend
- Growth / decline
- Volatility
- Seasonality
- Concentration

## Receivables

- Average collection delay
- Overdue invoices
- Outstanding receivables
- DSO-like metrics
- Changes in customer payment behavior

## Payables

- Supplier payment delays
- Outstanding payables
- Changes in payment behavior
- Increasing reliance on delaying suppliers

## Debt

- Total outstanding debt
- Debt trend
- Credit-line utilization
- Financing cost
- Upcoming repayments
- Debt service pressure

## Counterparty risk

- Customer concentration
- Supplier concentration
- Dependency on specific counterparties

## Behavioral changes

The model should focus heavily on **changes in behavior**, not only absolute values.

Examples:

- collection times suddenly increasing
- cash reserves consistently falling
- credit-line utilization increasing
- supplier payments becoming later
- inflows becoming more volatile

---

# 6. Explainability

The score cannot be a black box.

For every company we should be able to answer:

> Why does this company have this score?

and:

> Why did the score change?

Example:

    Financial Health Score

    68 / 100
    ↓ 7 points over 3 months

    Main negative drivers:

    - Cash buffer: 4.2 → 2.8 months
    - Average collection time: 38 → 52 days
    - Credit-line utilization: 41% → 67%

    Positive signals:

    - Revenue remains stable
    - Supplier concentration decreased

Explainability is a core part of the product.

---

# 7. Early Warning

One important objective is detecting changes **before they become obvious**.

Example:

    Month 1     82
    Month 2     81
    Month 3     80
    Month 4     77  ← Early warning
    Month 5     73
    Month 6     68

The system should ideally detect deterioration around Month 4 instead of waiting until Month 6.

We should measure:

> How many months earlier did we detect the change?

This is a bonus evaluation criterion.

---

# 8. Monitoring

The product should ideally be proactive.

Instead of requiring the user to inspect every company manually:

    ⚠ Financial deterioration detected

    Health Score: 74 → 66

    Main drivers:
    - Customer payment delays increasing
    - Cash buffer declining
    - Credit-line utilization increasing

This turns the system from an analytics dashboard into a **financial monitoring system**.

---

# 9. Product

## Working concept

# Embat X-Ray
### Financial Health Copilot / Early Warning System

The Financial Health Score is the underlying engine.

The actual product continuously analyzes the company's financial behavior and answers:

1. How healthy is my company?
2. Is it improving or deteriorating?
3. What is causing the change?
4. Is this temporary or structural?
5. What should I do about it?
6. Is there something I need to act on now?

---

# 10. Stakeholder / Buyer

## Primary buyer

**CFO / Finance Director**

The company already provides its financial data to Embat.

Therefore Embat can transform existing treasury data into financial intelligence without requiring the customer to provide additional information.

The CFO is willing to pay because the system helps identify financial problems and opportunities earlier.

---

# 11. End User

Primary users:

- CFO
- Finance Director
- Head of Finance
- Treasury Manager

These users already monitor:

- liquidity
- debt
- collections
- payments
- cash flow

The product adds an intelligence layer on top of those workflows.

---

# 12. User Problem

Finance teams already have dashboards showing:

> What happened?

The product should answer:

> What is changing?

> Why is it changing?

> What is likely to require my attention?

> What should I do next?

Core product philosophy:

> CFOs don't need another dashboard telling them what happened.
> They need to know what's starting to go wrong, why, and what to do about it.

---

# 13. Example Product Experience

The CFO opens Embat X-Ray.

## Overview

    FINANCIAL HEALTH

    72 / 100
    ↑ 4 points

    Improving

    ─────────────────────────

    Liquidity        81
    Cash Flow        76
    Receivables      63
    Debt             71
    Stability        75

Then:

## What changed?

    Your financial health improved
    by 4 points this month.

    Main drivers:

    + Cash position +12%
    + Late receivables -18%
    + Debt utilization stable

    Risk:

    - Customer concentration increased

Then:

## What needs attention?

    ⚠ €84k overdue from 4 customers

    ⚠ Customer ACME represents
      31% of monthly inflows

    ⚠ Credit line utilization
      increased from 48% → 61%

Then:

## Recommended actions

    1. Prioritize collection of €84k
       from overdue customers.

    2. Review dependency on ACME.

    3. Consider refinancing Loan X
       before its next payment period.

---

# 14. Product Flow

The complete system can be thought of as:

    Financial Data
          ↓
    Feature Engineering
          ↓
    Financial Signals
          ↓
    Financial Health Score
          ↓
    Trend Detection
          ↓
    Explainability
          ↓
    Early Warning
          ↓
    Recommendations
          ↓
    CFO Action

Short version:

**Data → Score → Detect → Explain → Recommend → Monitor**

---

# 15. Demo Story

The demo should tell a story instead of simply showing features.

Suggested flow:

### Step 1 — Company overview

Show:

    Financial Health: 76

At first everything appears fine.

### Step 2 — Timeline

Show the 24-month score evolution.

Example:

    84 → 83 → 81 → 78 → 75 → 72

The company is still relatively healthy but clearly deteriorating.

### Step 3 — Early warning

Show:

    ⚠ Deterioration detected 3 months ago

This demonstrates anticipation.

### Step 4 — Explain why

Example:

    Cash buffer            ↓ 23%
    Collection time        +14 days
    Credit utilization     +21%

### Step 5 — Ask the Copilot

Example question:

    "Why is our financial health deteriorating?"

Answer using the underlying financial signals.

### Step 6 — Recommended action

Show concrete actions.

This completes the transition:

**Data → Insight → Decision → Action**

---

# 16. Evaluation Criteria

The challenge evaluates three equally important dimensions.

## Accuracy

- Generalization
- Trajectory detection
- Improvement detection
- Deterioration detection

## Timing

- Early detection
- Stability
- Temporary vs structural changes
- Proactive monitoring

## Business Value

- Product
- Clear buyer
- Explainability
- Demo quality

Important:

A sophisticated ML model without a strong product is not enough.

A simpler model with:

- good signals
- strong explainability
- clear product
- clear buyer
- great demo

can be a stronger solution.

---

# 17. Mandatory Deliverables

The final solution must include:

- Prediction on hidden test companies
- Signals in both directions
- Trajectory-aware score
- Explainability
- Product built on top of the score
- Identified buyer
- Navigable demo

Bonus:

- Measured anticipation
- Proactive monitoring / alerts

---

# 18. North Star

When making product or technical decisions, optimize for:

> Can we detect a meaningful change in a company's financial health before it becomes obvious, explain exactly why it is happening, and help the CFO decide what to do next?

If a feature does not contribute to this, it is probably not essential for the hackathon.

---

# 19. One-Sentence Pitch

> Embat X-Ray continuously monitors a company's financial behavior, detects changes in financial health before they become obvious, explains what's driving them, and recommends what the finance team should do next.

---

# 20. Hackathon Priority

When choosing between features, prioritize:

**1. Reliable score**

**2. Clear trajectory**

**3. Explainability**

**4. Early-warning moment**

**5. Actionable recommendation**

**6. Strong visual demo**

Avoid spending excessive time on complexity that cannot be demonstrated or explained during the final pitch.
