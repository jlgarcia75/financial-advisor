#!/usr/bin/env python3
"""Reconcile manual statement CSVs with linked-account CSV exports."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import (  # noqa: E402
    first_value,
    normalize_text,
    parse_date,
    parse_number,
    read_csv,
    write_csv,
)

DEFAULT_MANUAL_DIR = Path('/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance/Reviews/inputs')
DEFAULT_OUTPUT_DIR = Path('/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance/Reviews/reconciliation')
DEFAULT_REVIEWS_DIR = Path('/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance/Reviews')

ACCOUNT_NAME_FIELDS = ('account_name', 'name', 'official_name')
ACCOUNT_ID_FIELDS = ('account_id', 'persistent_account_id', 'id')
ACCOUNT_TYPE_FIELDS = ('account_type', 'type', 'subtype')
INSTITUTION_FIELDS = ('institution', 'institution_name', 'provider', 'brokerage')
LAST4_FIELDS = ('account_last4', 'last4', 'mask')
SYMBOL_FIELDS = ('symbol', 'ticker_symbol', 'ticker')
SECURITY_NAME_FIELDS = ('security_name', 'name', 'description')
QUANTITY_FIELDS = ('quantity', 'shares')
VALUE_FIELDS = ('market_value', 'institution_value', 'current_value', 'value')
TX_DATE_FIELDS = ('date', 'posted_date', 'authorized_date', 'transaction_date')
TX_AMOUNT_FIELDS = ('amount', 'transaction_amount')
TX_DESC_FIELDS = ('merchant_name', 'description', 'name', 'security_name')
TX_ID_FIELDS = ('transaction_id', 'investment_transaction_id', 'id')


def normalize_account_type(value: Any) -> str:
    text = normalize_text(value)
    aliases = {
        'ira roth': 'roth_ira', 'roth ira': 'roth_ira',
        'ira rollover': 'rollover_ira', 'rollover ira': 'rollover_ira',
        'credit card': 'credit_card', 'credit': 'credit_card',
        '401 k': '401k',
    }
    return aliases.get(text, text.replace(' ', '_'))


def last4_from_row(row: dict[str, Any]) -> str:
    value = first_value(row, LAST4_FIELDS) or first_value(row, ACCOUNT_ID_FIELDS)
    digits = re.sub(r'\D', '', value)
    return digits[-4:] if len(digits) >= 4 else ''


def text_similarity(a: str, b: str) -> float:
    a_n, b_n = normalize_text(a), normalize_text(b)
    return SequenceMatcher(None, a_n, b_n).ratio() if a_n and b_n else 0.0


def account_view(row: dict[str, str]) -> dict[str, str]:
    return {
        'account_id': first_value(row, ACCOUNT_ID_FIELDS),
        'account_name': first_value(row, ACCOUNT_NAME_FIELDS),
        'institution': first_value(row, INSTITUTION_FIELDS),
        'account_type': normalize_account_type(first_value(row, ACCOUNT_TYPE_FIELDS)),
        'last4': last4_from_row(row),
    }


def score_accounts(manual: dict[str, str], linked: dict[str, str]) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    if manual['last4'] and manual['last4'] == linked['last4']:
        score += 45; reasons.append('same_last4')
    name_score = text_similarity(manual['account_name'], linked['account_name'])
    score += name_score * 30
    if name_score >= 0.85: reasons.append('very_similar_name')
    elif name_score >= 0.65: reasons.append('similar_name')
    inst_score = text_similarity(manual['institution'], linked['institution'])
    score += inst_score * 15
    if inst_score >= 0.75: reasons.append('similar_institution')
    if manual['account_type'] and manual['account_type'] == linked['account_type']:
        score += 10; reasons.append('same_account_type')
    if manual['account_id'] and normalize_text(manual['account_id']) == normalize_text(linked['account_id']):
        score = 100; reasons.append('same_account_id')
    return min(round(score, 2), 100.0), reasons


def match_accounts(manual_rows: list[dict[str, str]], linked_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    linked_views = [(row, account_view(row)) for row in linked_rows]
    results = []
    for row in manual_rows:
        manual = account_view(row)
        ranked = sorted((score_accounts(manual, view), raw, view) for raw, view in linked_views)
        if ranked:
            (score, reasons), _, best = ranked[-1]
        else:
            score, reasons, best = 0.0, [], {'account_id':'','account_name':'','institution':'','account_type':'','last4':''}
        status = 'exact_or_high_confidence' if score >= 85 else 'likely_match' if score >= 65 else 'possible_match' if score >= 45 else 'unmatched'
        results.append({
            'manual_account_id': manual['account_id'], 'manual_account_name': manual['account_name'],
            'manual_institution': manual['institution'], 'manual_account_type': manual['account_type'],
            'manual_last4': manual['last4'], 'linked_account_id': best['account_id'],
            'linked_account_name': best['account_name'], 'linked_institution': best['institution'],
            'linked_account_type': best['account_type'], 'linked_last4': best['last4'],
            'match_score': score, 'match_status': status, 'match_reasons': '|'.join(reasons),
            'review_required': status in {'likely_match','possible_match'},
        })
    return results


def account_map(matches: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for match in matches:
        if match['match_status'] in {'exact_or_high_confidence','likely_match'}:
            m = match['manual_account_id'] or normalize_text(match['manual_account_name'])
            l = match['linked_account_id'] or normalize_text(match['linked_account_name'])
            result[m] = l
    return result


def holding_key(row: dict[str, str], account_override: str | None = None) -> tuple[str, str]:
    account = account_override or first_value(row, ACCOUNT_ID_FIELDS) or normalize_text(first_value(row, ACCOUNT_NAME_FIELDS))
    symbol = normalize_text(first_value(row, SYMBOL_FIELDS)) or normalize_text(first_value(row, SECURITY_NAME_FIELDS))
    return account, symbol


def reconcile_holdings(manual_rows, linked_rows, matches, value_tolerance, quantity_tolerance):
    amap = account_map(matches)
    index = defaultdict(list)
    for row in linked_rows: index[holding_key(row)].append(row)
    results = []
    for manual in manual_rows:
        m_account = first_value(manual, ACCOUNT_ID_FIELDS) or normalize_text(first_value(manual, ACCOUNT_NAME_FIELDS))
        candidates = index.get(holding_key(manual, amap.get(m_account,'')), [])
        best = candidates[0] if candidates else {}
        mq, lq = parse_number(first_value(manual, QUANTITY_FIELDS)), parse_number(first_value(best, QUANTITY_FIELDS))
        mv, lv = parse_number(first_value(manual, VALUE_FIELDS)), parse_number(first_value(best, VALUE_FIELDS))
        qd = abs(mq-lq) if mq is not None and lq is not None else None
        vd = abs(mv-lv) if mv is not None and lv is not None else None
        if not best: status = 'manual_only'
        elif (qd is None or qd <= quantity_tolerance) and (vd is None or vd <= value_tolerance): status = 'probable_duplicate'
        else: status = 'matched_position_with_difference'
        results.append({
            'manual_account_id': first_value(manual, ACCOUNT_ID_FIELDS),
            'manual_account_name': first_value(manual, ACCOUNT_NAME_FIELDS),
            'linked_account_id': first_value(best, ACCOUNT_ID_FIELDS),
            'linked_account_name': first_value(best, ACCOUNT_NAME_FIELDS),
            'symbol': first_value(manual, SYMBOL_FIELDS),
            'security_name': first_value(manual, SECURITY_NAME_FIELDS),
            'manual_quantity': mq, 'linked_quantity': lq, 'quantity_delta': qd,
            'manual_market_value': mv, 'linked_market_value': lv, 'market_value_delta': vd,
            'reconciliation_status': status,
            'exclude_manual_from_combined_view': status == 'probable_duplicate',
            'review_required': status == 'matched_position_with_difference',
        })
    return results


def tx_fingerprint(row: dict[str,str], account_override: str | None = None) -> str:
    account = account_override or first_value(row, ACCOUNT_ID_FIELDS) or normalize_text(first_value(row, ACCOUNT_NAME_FIELDS))
    date = parse_date(first_value(row, TX_DATE_FIELDS))
    amount = parse_number(first_value(row, TX_AMOUNT_FIELDS))
    desc = normalize_text(first_value(row, TX_DESC_FIELDS))
    raw = f"{normalize_text(account)}|{date}|{'' if amount is None else f'{amount:.2f}'}|{desc}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def reconcile_transactions(manual_rows, linked_rows, matches, amount_tolerance, description_threshold):
    amap = account_map(matches)
    index = defaultdict(list)
    for row in linked_rows:
        account = first_value(row, ACCOUNT_ID_FIELDS) or normalize_text(first_value(row, ACCOUNT_NAME_FIELDS))
        index[(account, parse_date(first_value(row, TX_DATE_FIELDS)))].append(row)
    results = []
    for manual in manual_rows:
        m_account = first_value(manual, ACCOUNT_ID_FIELDS) or normalize_text(first_value(manual, ACCOUNT_NAME_FIELDS))
        linked_account = amap.get(m_account,'')
        date = parse_date(first_value(manual, TX_DATE_FIELDS))
        ma = parse_number(first_value(manual, TX_AMOUNT_FIELDS)); md = first_value(manual, TX_DESC_FIELDS)
        ranked = []
        for candidate in index.get((linked_account,date),[]):
            la = parse_number(first_value(candidate, TX_AMOUNT_FIELDS))
            delta = abs(ma-la) if ma is not None and la is not None else math.inf
            sim = text_similarity(md, first_value(candidate, TX_DESC_FIELDS))
            ranked.append((delta,-sim,candidate))
        ranked.sort(key=lambda x:(x[0],x[1])); best = ranked[0][2] if ranked else {}
        la = parse_number(first_value(best, TX_AMOUNT_FIELDS)); delta = abs(ma-la) if ma is not None and la is not None else None
        sim = text_similarity(md, first_value(best, TX_DESC_FIELDS)) if best else 0.0
        if not best: status = 'manual_only'
        elif delta is not None and delta <= amount_tolerance and sim >= description_threshold: status = 'probable_duplicate'
        elif delta is not None and delta <= amount_tolerance: status = 'possible_duplicate_description_differs'
        else: status = 'unmatched_or_changed'
        results.append({
            'manual_transaction_id': first_value(manual, TX_ID_FIELDS),
            'linked_transaction_id': first_value(best, TX_ID_FIELDS),
            'manual_account_id': first_value(manual, ACCOUNT_ID_FIELDS),
            'linked_account_id': first_value(best, ACCOUNT_ID_FIELDS),
            'date': date, 'manual_description': md,
            'linked_description': first_value(best, TX_DESC_FIELDS),
            'manual_amount': ma, 'linked_amount': la, 'amount_delta': delta,
            'description_similarity': round(sim,4),
            'manual_fingerprint': tx_fingerprint(manual, linked_account),
            'linked_fingerprint': tx_fingerprint(best) if best else '',
            'reconciliation_status': status,
            'exclude_manual_from_combined_view': status == 'probable_duplicate',
            'review_required': status in {'possible_duplicate_description_differs','unmatched_or_changed'},
        })
    return results


def count_by(rows, field):
    counts = defaultdict(int)
    for row in rows: counts[str(row.get(field,''))] += 1
    return dict(sorted(counts.items()))


# Canonical account-level statuses (architecture doc contract):
#   manual_only, linked_only, probable_duplicate, confirmed_duplicate, needs_review
# confirmed_duplicate is set by a human after review; it is never auto-assigned.
def _canonical_status(match: dict[str, Any]) -> tuple[str, str]:
    ms = match['match_status']
    if ms == 'exact_or_high_confidence':
        return 'probable_duplicate', 'High-confidence match; exclude the manual account from the combined view to avoid double-counting.'
    if ms in {'likely_match', 'possible_match'}:
        return 'needs_review', 'Fuzzy match; confirm whether these are the same account before merging.'
    return 'manual_only', 'No linked counterpart found; keep the manual account.'


def build_account_reconciliation(matches: list[dict[str, Any]], linked_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """One row per account across both sources, with the canonical status enum."""
    rows: list[dict[str, Any]] = []
    claimed: set[str] = set()
    for match in matches:
        status, note = _canonical_status(match)
        if status in {'probable_duplicate', 'needs_review'} and match['linked_account_id']:
            claimed.add(normalize_text(match['linked_account_id']))
            claimed.add(normalize_text(match['linked_account_name']))
        rows.append({
            'account_key': match['manual_account_id'] or normalize_text(match['manual_account_name']),
            'manual_account_id': match['manual_account_id'],
            'manual_account_name': match['manual_account_name'],
            'linked_account_id': match['linked_account_id'] if status != 'manual_only' else '',
            'linked_account_name': match['linked_account_name'] if status != 'manual_only' else '',
            'institution': match['manual_institution'] or match['linked_institution'],
            'match_score': match['match_score'],
            'status': status,
            'source_priority_hint': 'manual_statement' if status == 'probable_duplicate' else '',
            'review_required': status in {'needs_review'},
            'notes': note,
        })
    for linked in linked_rows:
        view = account_view(linked)
        key_id, key_name = normalize_text(view['account_id']), normalize_text(view['account_name'])
        if (key_id and key_id in claimed) or (key_name and key_name in claimed):
            continue
        rows.append({
            'account_key': view['account_id'] or key_name,
            'manual_account_id': '', 'manual_account_name': '',
            'linked_account_id': view['account_id'], 'linked_account_name': view['account_name'],
            'institution': view['institution'],
            'match_score': 0.0, 'status': 'linked_only',
            'source_priority_hint': 'linked', 'review_required': False,
            'notes': 'Only present in linked data; keep the linked account.',
        })
    return rows


def resolve_period(manual_accounts: list[dict[str, str]], override: str | None) -> str:
    if override:
        return override
    periods = []
    for row in manual_accounts:
        iso = parse_date(first_value(row, ('as_of_date',))) or first_value(row, ('statement_id',))[:7]
        m = re.match(r'(\d{4}-\d{2})', iso)
        if m:
            periods.append(m.group(1))
    return max(periods) if periods else datetime.now().astimezone().strftime('%Y-%m')


def write_reconciliation_review_md(path: Path, period: str, account_recon: list[dict[str, Any]],
                                   holdings: list[dict[str, Any]], transactions: list[dict[str, Any]]) -> None:
    status_counts = count_by(account_recon, 'status')
    lines = [
        f'# {period} Reconciliation Review',
        '',
        'Manual (Empower/Pershing) statement data vs. linked-account exports. This file is a',
        'human review layer — resolve every `needs_review` account before trusting the combined',
        'net-worth view.',
        '',
        '## Account status summary',
        '',
        '| Status | Count |',
        '| --- | --- |',
    ]
    for status, count in status_counts.items():
        lines.append(f'| {status} | {count} |')
    lines += ['', '## Accounts needing review', '']
    review = [r for r in account_recon if r['review_required']]
    if review:
        lines += ['| Manual account | Linked account | Score | Note |', '| --- | --- | --- | --- |']
        for r in review:
            lines.append(f"| {r['manual_account_name']} | {r['linked_account_name']} | {r['match_score']} | {r['notes']} |")
    else:
        lines.append('_None — all accounts auto-classified._')

    dup_holdings = [h for h in holdings if h['reconciliation_status'] == 'probable_duplicate']
    diff_holdings = [h for h in holdings if h['reconciliation_status'] == 'matched_position_with_difference']
    dup_tx = [t for t in transactions if t['reconciliation_status'] == 'probable_duplicate']
    lines += [
        '',
        '## Overlap detail',
        '',
        f'- Holdings flagged as probable duplicates (excluded from combined view): **{len(dup_holdings)}**',
        f'- Holdings matched but with a value/quantity difference (review): **{len(diff_holdings)}**',
        f'- Transactions flagged as probable duplicates: **{len(dup_tx)}**',
        '',
        '## Policy',
        '',
        '- `probable_duplicate` — excluded from the combined view; retained in audit CSVs.',
        '- `manual_only` / `linked_only` — kept as-is.',
        '- `needs_review` — never auto-merged. Confirm, then set the account note `source_priority`',
        '  and (optionally) change this status to `confirmed_duplicate`.',
        '',
        '_See `reconciliation/` for the full per-domain overlap CSVs._',
        '',
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description='Reconcile manual statement CSVs with linked-account CSV exports.')
    parser.add_argument('--manual-dir', type=Path, default=DEFAULT_MANUAL_DIR)
    parser.add_argument('--linked-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--reviews-dir', type=Path, default=DEFAULT_REVIEWS_DIR,
                        help='Where canonical review artifacts are written (default: Reviews/).')
    parser.add_argument('--period', help='YYYY-MM for the review filename (default: latest manual as_of_date).')
    parser.add_argument('--manual-accounts', type=Path)
    parser.add_argument('--manual-holdings', type=Path)
    parser.add_argument('--manual-transactions', type=Path)
    parser.add_argument('--linked-accounts', type=Path)
    parser.add_argument('--linked-holdings', type=Path)
    parser.add_argument('--linked-transactions', type=Path)
    parser.add_argument('--holding-value-tolerance', type=float, default=5.0)
    parser.add_argument('--holding-quantity-tolerance', type=float, default=0.001)
    parser.add_argument('--transaction-amount-tolerance', type=float, default=0.01)
    parser.add_argument('--description-threshold', type=float, default=0.65)
    args = parser.parse_args()

    ma_path = args.manual_accounts or args.manual_dir/'manual_statements_master_accounts.csv'
    mh_path = args.manual_holdings or args.manual_dir/'manual_statements_master_holdings.csv'
    mt_path = args.manual_transactions or args.manual_dir/'manual_statements_master_transactions.csv'
    la_path = args.linked_accounts or args.linked_dir/'linked_accounts.csv'
    lh_path = args.linked_holdings or args.linked_dir/'linked_holdings.csv'
    lt_path = args.linked_transactions or args.linked_dir/'linked_transactions.csv'

    missing = [p for p in (ma_path, la_path) if not p.exists()]
    if missing:
        for p in missing: print(f'Missing required input: {p}', file=sys.stderr)
        return 2

    ma, mh, mt = read_csv(ma_path), read_csv(mh_path), read_csv(mt_path)
    la, lh, lt = read_csv(la_path), read_csv(lh_path), read_csv(lt_path)
    matches = match_accounts(ma, la)
    holdings = reconcile_holdings(mh, lh, matches, args.holding_value_tolerance, args.holding_quantity_tolerance)
    transactions = reconcile_transactions(mt, lt, matches, args.transaction_amount_tolerance, args.description_threshold)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir/'account_matches.csv', matches)
    write_csv(args.output_dir/'holding_overlaps.csv', holdings)
    write_csv(args.output_dir/'transaction_overlaps.csv', transactions)
    summary = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'row_counts': {'manual_accounts':len(ma),'linked_accounts':len(la),'manual_holdings':len(mh),'linked_holdings':len(lh),'manual_transactions':len(mt),'linked_transactions':len(lt)},
        'account_match_status': count_by(matches,'match_status'),
        'holding_reconciliation_status': count_by(holdings,'reconciliation_status'),
        'transaction_reconciliation_status': count_by(transactions,'reconciliation_status'),
        'policy': {
            'probable_duplicate':'Exclude manual row from combined view but keep it in audit files.',
            'manual_only':'Keep the manual row.',
            'review_required':'Do not merge automatically.'
        }
    }
    (args.output_dir/'reconciliation_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')

    # Canonical, downstream-facing artifacts (architecture doc contract).
    period = resolve_period(ma, args.period)
    account_recon = build_account_reconciliation(matches, la)
    write_csv(
        args.manual_dir/'manual_linked_reconciliation.csv',
        account_recon,
        preferred=['account_key', 'manual_account_id', 'manual_account_name',
                   'linked_account_id', 'linked_account_name', 'institution',
                   'match_score', 'status', 'source_priority_hint', 'review_required', 'notes'],
    )
    review_md = args.reviews_dir/f'{period}_reconciliation_review.md'
    write_reconciliation_review_md(review_md, period, account_recon, holdings, transactions)

    print(f'Wrote reconciliation outputs to {args.output_dir}')
    print(f'Wrote canonical reconciliation CSV to {args.manual_dir/"manual_linked_reconciliation.csv"}')
    print(f'Wrote review to {review_md}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
