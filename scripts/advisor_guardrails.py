"""Shared advisor guardrails.

Both the tax-strategy prompt (create_tax_strategy_prompt.py) and the vault briefing
(build_advisor_briefing.py) embed these, so the tagging / ranking / entity rules
cannot drift between the ChatGPT Project instructions and the per-domain prompts.
Household-specific facts (filing status, the trust's revocable/grantor character,
carryovers) live in tax_profile.md, not here — this stays general.
"""

GUARDRAILS = """- Tag every claim as [DATA] (from the figures provided), [ASSUMPTION] (yours, stated), or [RULE] (a general rule to verify). Show the math for any dollar figure.
- Rank recommendations by estimated after-tax $ impact AND deadline; call out hard deadlines.
- Scope advice per entity/return. For any grantor trust in scope, its income is reported on the grantor's personal 1040 — do NOT apply separate Form 1041 trust brackets or a distribution deduction. Keep income-tax treatment distinct from estate/gift-tax treatment (a revocable trust's assets stay in the estate and get a §1014 basis step-up at death; an irrevocable IDGT's do not).
- Verify anything tax-law-specific against current IRS / state guidance or a CPA before acting.
- End with: (a) the assumptions you made, and (b) the missing data that would most change your advice."""
