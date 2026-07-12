# Tax Strategy Prompt

A reusable, data-grounded prompt for getting proactive tax strategy from an LLM advisor
(e.g. your ChatGPT project). It is deliberately **not** a blank questionnaire: you paste in
the exact figures the pipeline already produces, so the advisor reasons about your real
accounts instead of improvising.

This is a manual template for now. If you later want it generated automatically from the
pipeline, see the deferred `create_tax_strategy_prompt.py` idea in the architecture notes.

## How to use

1. Refresh the combined view first so the numbers are current:
   `python3 scripts/ingest_linked_export.py` (or `build_finance_dashboard.py`).
2. Fill in the **Household profile** block below from your own records (this is the one part
   the pipeline can't supply — see the profile checklist).
3. Fill the **Accounts & positions** block from these generated files (attach them too):
   - `Reviews/networth_breakdown.csv` — net worth by tax treatment and owner
   - `Reviews/NET_WORTH_snapshot.csv` — per-account value, type, tax treatment, owner, as-of
   - `Reviews/allocation_summary.csv` — allocation by asset class / account type
   - `Reviews/inputs/manual_statements_master_transactions.csv` — dividends, fees, buys/sells
   - `Reviews/inputs/manual_statements_master_activity.csv` — YTD income/expense metrics
4. Paste the prompt into the advisor and attach the CSVs above.
5. Save the response to `Reviews/<YEAR>_tax_strategy_review.md`.

### Privacy
Use aggregates and `account_last4` only. Never paste full account numbers, SSNs, or
credentials. The CSVs above already follow this convention.

### Cadence
- **Year-end (Oct–Dec):** full run — most strategies (TLH, Roth conversions, charitable,
  contributions) have a Dec 31 or filing-deadline window.
- **Quarterly:** a lighter run focused on estimated payments and any realized gains to date.

## Household profile checklist (fill from your records)

The pipeline does not know these — maintain them yourself (a `tax_profile.md` note in the
vault is a good home):

- Filing status, state, dependents, taxpayers (e.g. MFJ — Jesus & LeAndra)
- Entities / returns in scope (e.g. Personal MFJ; The Garcia Family Trust)
- Estimated AGI/MAGI; marginal and effective bracket
- YTD wages and withholding; estimated payments already made; prior-year AGI
- Carryovers (capital loss, charitable)
- Current-year tax constants from irs.gov (standard deduction, brackets, 401k/IRA/HSA
  limits, LTCG thresholds). If you leave these blank, the prompt forces the model to state
  its assumptions and mark them VERIFY.

## Known data gap: cost basis

The statement extractor does not capture tax-lot cost basis, so **realized gains/losses and
tax-loss-harvesting cannot be quantified from pipeline data alone**. Until a 1099-B /
consolidated 1099 ingestion path exists, either attach your year-end 1099-B or tell the
advisor cost basis is unavailable (the prompt already instructs it to flag this).

---

## The prompt

```text
ROLE
You are a tax-planning analyst helping a household with proactive, year-round tax strategy.
You are NOT filing a return and NOT giving legal advice. Be concrete and quantitative, but
flag uncertainty instead of guessing.

TAX YEAR & GROUND RULES
- Tax year: <YEAR>. Current-year constants I'm providing (leave blank if unknown):
  standard deduction <>, brackets <>, 401k/IRA/HSA limits <>, LTCG thresholds <>.
  If any constant is blank or looks wrong for <YEAR> given your knowledge cutoff, state the
  value you're assuming and mark it "VERIFY" — never silently use stale numbers.
- Tag every claim as [DATA] (from my figures), [ASSUMPTION] (yours, stated explicitly), or
  [RULE] (a general tax rule to verify). Show the math for any dollar figure.
- Rank recommendations by estimated after-tax $ impact AND deadline; call out hard deadlines.
- Scope advice per entity/return; do not blend the personal return with the trust.
- End with: (a) the assumptions you made, and (b) the specific missing data that would most
  change your advice.

HOUSEHOLD PROFILE
- Filing status: <>; State: <>; Dependents: <>; Taxpayers: <>
- Entities / returns in scope: <Personal (MFJ)>, <The Garcia Family Trust>
- Est. AGI/MAGI: <>; marginal / effective bracket: <>
- YTD wages & withholding: <>; estimated payments made: <>; prior-year AGI: <>
- Carryovers: capital loss <>, charitable <>

ACCOUNTS & POSITIONS  (authoritative, deduplicated — see attached CSVs)
- Net worth by tax treatment: taxable <>, tax-deferred <>, tax-free <>   [networth_breakdown.csv]
- Accounts (owner, type, tax treatment, value, as-of):                    [NET_WORTH_snapshot.csv]
- Allocation by asset class:                                              [allocation_summary.csv]
- YTD dividends <>, interest <>, fees <>; realized gains/losses:
  <amount, or "NOT AVAILABLE — no cost basis in pipeline">               [transactions/activity]
- Inherited IRAs subject to the 10-year rule: Inherited Traditional <>, Inherited Roth <>

DELIVERABLES  (as a prioritized, deadline-tagged action plan)
1. Top strategies ranked by after-tax $ impact — each with the move, estimated savings,
   deadline, target account/entity, and a one-line rationale. Consider at least:
   - Asset location across taxable / tax-deferred / tax-free accounts
   - Roth conversion sizing to fill lower brackets (given the deferred vs free split)
   - Tax-loss harvesting candidates (or state why not, if cost basis is unavailable)
   - Inherited-IRA distribution plan under the 10-year rule (with any annual RMDs)
   - Retirement / HSA contribution room and backdoor/mega-backdoor Roth eligibility
   - Charitable strategy (bunching, donor-advised fund, qualified charitable distributions)
   - Trust-vs-personal income placement (trusts hit top brackets at low income)
2. Estimated tax liability under 2–3 scenarios (baseline vs recommended), with the math.
3. Quarterly estimated-payment guidance and a safe-harbor check for the rest of <YEAR>.
4. State-specific considerations for <STATE> (and community-property notes if relevant).
5. Documents to gather (W-2s, 1099-DIV/B/INT, K-1s, prior return) and common mistakes for
   this profile.
6. Whether this profile needs a CPA vs tax software, and why.
7. What data is missing that would most sharpen this analysis (especially cost basis /
   realized gains).

VERIFY EVERYTHING TAX-LAW-SPECIFIC AGAINST CURRENT IRS/STATE GUIDANCE OR A CPA BEFORE ACTING.
```

## Why the guardrails

- **VERIFY tags + explicit constants** prevent the model from asserting stale bracket/limit
  numbers as fact — tax parameters change every year and the model's training may lag.
- **[DATA] / [ASSUMPTION] / [RULE] tagging + "show the math"** keeps your real figures
  separate from the model's guesses so every number is auditable.
- **Entity scoping** matters because the trust is a separate taxpayer with compressed
  brackets; blending it with the MFJ return produces wrong advice.
- **Deadline ranking** turns a generic deduction list into an actionable, time-boxed plan.
- **"List missing data"** makes the model tell you where better inputs (e.g. cost basis)
  would change the answer, instead of quietly guessing.
