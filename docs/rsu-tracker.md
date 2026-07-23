# RSU / Equity-Compensation Tracker

Unvested RSUs are **contingent future compensation, not an owned asset** — they forfeit if
you leave before each vest date, and they become **ordinary income (added to W-2 wages) at
vest**. So they are deliberately kept *out* of the owned-asset rollups (net worth, allocation)
and tracked here instead, for income projection and tax planning.

See the E\*TRADE Stock Plan account note (`Accounts/etrade-stock-plan-intc.md`,
`include_in_networth: false`) for why the unvested position is excluded from the dashboard.

## Where the file goes

```text
~/ObsidianVaults/second-brain/91_finance/equity_comp/
└── rsu_vesting.csv        # one row per vest tranche (dates + shares)
```

Vault-only (gitignored), never in the repo. Validated by
`schemas/equity-comp/rsu-vesting.schema.json`.

## Columns

`symbol, grant_id, grant_date, vest_date, shares, status, price_per_share, source, notes`

| Field | Notes |
|---|---|
| `symbol` | Ticker, e.g. `INTC`. Required. |
| `grant_id` | E\*TRADE grant identifier (optional, groups tranches of one grant). |
| `grant_date` | `YYYY-MM-DD` the grant was awarded (optional). |
| `vest_date` | `YYYY-MM-DD` this tranche vests. Blank = unscheduled (flagged in the prompt). |
| `shares` | Shares vesting on that date. Required. |
| `status` | `unvested` (future) or `vested` (already released — kept for history). |
| `price_per_share` | For `unvested` rows: assumed current price (flat) for projecting income. For `vested` rows: the actual FMV at vest. |
| `source` | `etrade` / `manual`. |
| `notes` | Free text. |

**No account numbers or SSNs** — a ticker, dates, and share counts only.

## How future vests are valued

The tax prompt projects vest income as `shares × price_per_share`. For future vests the price
is an **assumption** (today's market price held flat), so it is tagged `[ASSUMPTION] / VERIFY`.
To reprice every future vest of a symbol at generation time without editing rows:

```bash
python3 scripts/create_tax_strategy_prompt.py --rsu-price INTC=109.83
```

`--rsu-price SYMBOL=PRICE` (repeatable) overrides `price_per_share` for all **unvested** rows of
that symbol. Actual income is always the FMV on the real vest date — projections are planning
estimates only.

## Workflow

1. In E\*TRADE (Stock Plan → **Holdings / Releases / Vesting Schedule**), read your unvested
   vest tranches: grant, vest date, shares.
2. Fill one row per tranche in `equity_comp/rsu_vesting.csv` (replace the scaffold aggregate
   row). Set `status: unvested` and `price_per_share` to the current market price.
3. Regenerate the tax prompt:

   ```bash
   python3 scripts/create_tax_strategy_prompt.py
   # or reprice at generation: --rsu-price INTC=<current price>
   ```

   The prompt gains an **EQUITY COMPENSATION — RSUs** section: unvested total plus projected
   ordinary income by tax year, feeding the AGI / safe-harbor discussion.
4. After a tranche vests, set its `status: vested` and `price_per_share` to the actual FMV at
   vest (the vested shares then count as real assets via your brokerage account, so there is no
   double-count).
