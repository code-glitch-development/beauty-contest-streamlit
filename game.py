"""Commit/reveal protocol and deterministic latest-attempt consensus."""
import csv
import hashlib
import io
import math
from datetime import datetime, timezone
from statistics import mean
from urllib.parse import urlparse

API_DEFAULT = 'https://script.google.com/macros/s/AKfycbyNZNOE1DYNbd4GbGTISJsGrnJ4PYCuip0yjSw3Lr8KkD6-kadKI9mfpKNfiAHEWb0Osw/exec'
DEADLINE = datetime(2026, 11, 15, 22, 59, 59, tzinfo=timezone.utc)
REVEAL_OPEN = datetime(2026, 11, 15, 23, 0, 0, tzinfo=timezone.utc)


def commitment(uid, number, nonce):
    return hashlib.sha256(f'{uid}|{number}|{nonce}'.encode('utf-8')).hexdigest()


def validate(uid, number, nonce):
    uid, nonce = uid.strip(), nonce.strip()
    if not uid:
        raise ValueError('Enter your University ID.')
    if not nonce:
        raise ValueError('Enter a secret nonce.')
    if '|' in uid or '|' in nonce:
        raise ValueError('University ID and nonce cannot contain the | character.')
    if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 100:
        raise ValueError('Your number must be an integer from 0 to 100.')
    return uid, number, nonce


def parse_ts(value):
    try:
        ts = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
        # A timestamp without an offset has no reliable position in the ledger.
        return ts.astimezone(timezone.utc) if ts.tzinfo else None
    except (TypeError, ValueError):
        return None


def consensus(commits, reveals):
    by_uid, latest, issues = {}, {}, []
    for row in commits:
        uid = str(row.get('uni_id', '')).strip()
        ts = parse_ts(row.get('timestamp_utc'))
        if not uid or ts is None:
            issues.append({'University ID': uid, 'Issue': 'Commit has missing ID or invalid timestamp'})
            continue
        by_uid.setdefault(uid, []).append((ts, row))
    for row in reveals:
        uid = str(row.get('uni_id', '')).strip()
        ts = parse_ts(row.get('timestamp_utc'))
        if not uid or ts is None:
            issues.append({'University ID': uid, 'Issue': 'Reveal has missing ID or invalid timestamp'})
            continue
        if uid not in latest or ts >= latest[uid][0]:
            latest[uid] = (ts, row)
    results = []
    for uid, (ts, row) in latest.items():
        candidates = [(t, i, c) for i, (t, c) in enumerate(by_uid.get(uid, [])) if t <= ts]
        chosen = max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None
        try:
            number = int(str(row.get('number', '')).strip())
        except ValueError:
            number = None
        nonce = str(row.get('nonce', '')).strip()
        reason = 'Verified'
        if chosen is None:
            reason = 'No commit before reveal'
        elif number is None:
            reason = 'Number is not an integer'
        elif not 0 <= number <= 100:
            reason = 'Number is outside 0–100'
        elif not nonce:
            reason = 'Missing nonce'
        elif commitment(uid, number, nonce) != str(chosen.get('commit', '')).strip():
            reason = 'Hash mismatch'
        results.append({'University ID': uid, 'Number': number, 'Status': reason,
                        'Revealed at (UTC)': ts.isoformat(), 'Distance': None, 'Rank': None})
    valid = [r for r in results if r['Status'] == 'Verified']
    avg = mean(r['Number'] for r in valid) if valid else None
    target = avg * (2 / 3) if avg is not None else None
    for row in valid:
        row['Distance'] = abs(row['Number'] - target)
    valid.sort(key=lambda row: (row['Distance'], row['University ID']))
    rank, previous = 0, None
    for i, row in enumerate(valid, 1):
        if previous is None or not math.isclose(row['Distance'], previous, rel_tol=0, abs_tol=1e-12):
            rank = i
        row['Rank'] = rank
        previous = row['Distance']
    results.sort(key=lambda row: (row['Rank'] is None, row['Distance'] if row['Distance'] is not None else math.inf, row['University ID']))
    return {'rows': results, 'issues': issues, 'average': avg, 'target': target,
            'count': len(valid), 'winners': [r['University ID'] for r in valid if r['Rank'] == 1]}


def csv_bytes(rows, fields=None):
    output = io.StringIO(newline='')
    fields = fields or (list(rows[0]) if rows else ['Rank', 'University ID', 'Number', 'Distance', 'Status'])
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')


def check_api(api):
    parsed = urlparse(api)
    if parsed.scheme != 'https' or parsed.hostname != 'script.google.com' or not parsed.path.startswith('/macros/s/') or not parsed.path.endswith('/exec') or parsed.query or parsed.fragment:
        raise ValueError('Use a Google Apps Script HTTPS deployment URL ending in /exec, without query parameters.')


def fetch_table(api, table):
    import requests
    check_api(api)
    if table not in {'commits', 'reveals'}:
        raise ValueError('Unknown ledger table.')
    response = requests.get(api, params={'table': table}, timeout=20)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text.lstrip('\ufeff')))
    required = {'timestamp_utc', 'uni_id', 'commit'} if table == 'commits' else {'timestamp_utc', 'uni_id', 'number', 'nonce'}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError(f'The {table} endpoint did not return the expected CSV columns. Check deployment access and the API URL.')
    return list(reader)


def submit(api, payload, now=None):
    import requests
    check_api(api)
    now = now or datetime.now(timezone.utc)
    if payload['kind'] == 'commit' and now > DEADLINE:
        raise ValueError('The commit window is closed.')
    if payload['kind'] == 'reveal' and now < REVEAL_OPEN:
        raise ValueError('The reveal window is not open yet.')
    # POST is deliberately never retried: the server is append-only.
    response = requests.post(api, json=payload, timeout=20)
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        status = str(data.get('status', '')).lower()
        if data.get('error') or data.get('ok') is False or data.get('success') is False or status in {'error', 'failed', 'failure'}:
            raise ValueError('Server rejected the submission. ' + str(data.get('error') or data.get('message') or 'Check your inputs.'))
        if data.get('ok') is True or data.get('success') is True or status in {'ok', 'success'}:
            return 'confirmed'
    # Unknown response formats must not be treated as proof of acceptance.
    return 'unconfirmed'


def demo_data():
    commits, reveals = [], []
    for uid, number, nonce in [('STU-001', 21, 'demo-a'), ('STU-002', 33, 'demo-b'), ('STU-003', 18, 'demo-c'), ('STU-004', 42, 'demo-d'), ('STU-005', 26, 'demo-e')]:
        commits.append({'uni_id': uid, 'commit': commitment(uid, number, nonce), 'timestamp_utc': '2026-11-14T12:00:00Z'})
        reveals.append({'uni_id': uid, 'number': str(number), 'nonce': nonce, 'timestamp_utc': '2026-11-16T09:00:00Z'})
    return commits, reveals
