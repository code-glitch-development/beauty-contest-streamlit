"""English Streamlit interface for the supplied Beauty Contest protocol."""
import json
import os
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from game import (API_DEFAULT, DEADLINE, REVEAL_OPEN, commitment, consensus,
                  csv_bytes, demo_data, fetch_table, submit, validate,
                  filter_leaderboard_reveals, leaderboard_consensus, LEADERBOARD_WINDOW_LABEL)

st.set_page_config(page_title='Beauty Contest | NEOMA', page_icon='🎯', layout='wide')
st.markdown('''<style>
.block-container {max-width:1180px;padding-top:2.8rem;padding-bottom:3rem}
[data-testid="stAppViewContainer"] {background:#f6f8fc}
[data-testid="stSidebar"] {background:#edf1f8}
h1,h2,h3 {letter-spacing:-.035em;color:#16233c}
[data-testid="stMetric"] {background:white;border:1px solid #e0e6f0;border-radius:14px;padding:18px}
[data-testid="stMetricLabel"] {color:#586780}
.stButton button, .stDownloadButton button {border-radius:9px}
[data-baseweb="tab-list"] {gap:28px;margin-top:12px}
[data-baseweb="tab"] {font-weight:650}
.eyebrow {font-size:12px;letter-spacing:.16em;color:#566b98;font-weight:700;margin-bottom:10px}
.subtitle {color:#64718a;font-size:17px;max-width:720px;line-height:1.65}
</style>''', unsafe_allow_html=True)

# Configuration belongs to the deployment, not to a public participant control.
def setting(name, fallback):
    try:
        return st.secrets.get(name, os.environ.get(name, fallback))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return os.environ.get(name, fallback)

api = str(setting('BEAUTY_API_URL', API_DEFAULT)).strip()
demo = st.sidebar.toggle('Demo mode', value=False, help='Use sample data and try both forms. No API requests are made.')
scope = 'demo' if demo else api
if st.session_state.get('scope') != scope:
    for key in ('snapshot', 'receipt', 'notice'):
        st.session_state.pop(key, None)
    # Do not carry a real nonce or ID into the demo, or demo inputs into live mode.
    for key in list(st.session_state):
        if key.startswith(('commit_', 'reveal_')):
            del st.session_state[key]
    st.session_state.scope = scope
if demo and 'demo_commits' not in st.session_state:
    st.session_state.demo_commits, st.session_state.demo_reveals = demo_data()

now = datetime.now(timezone.utc)
commit_open = demo or now <= DEADLINE
reveal_open = demo or now >= REVEAL_OPEN
with st.sidebar:
    st.markdown('### NEOMA Business School')
    st.caption('FINTECH & DEFI · CLASSROOM EXPERIMENT')
    st.divider()
    st.markdown('**How to play**')
    st.write('1. Choose an integer from 0 to 100.\n2. Commit a hash of your choice.\n3. Reveal your number and nonce.\n4. Get as close as possible to ⅔ of the class average.')
    st.divider()
    st.caption('COMMIT DEADLINE · PARIS')
    st.write('15 Nov 2026 · 23:59:59')
    st.caption('REVEAL OPENS · PARIS')
    st.write('16 Nov 2026 · 00:00:00')
    st.caption('Server time: ' + now.astimezone(ZoneInfo('Europe/Paris')).strftime('%d %b %Y · %H:%M:%S %Z'))
    st.divider()
    st.caption('Only your ID and hash are sent during commit. Your number and nonce become public when you reveal.')

st.markdown('<div class="eyebrow">GAME THEORY MEETS BLOCKCHAIN</div>', unsafe_allow_html=True)
st.title('The Beauty Contest')
st.markdown('<p class="subtitle">Think one step ahead. Predict the crowd, seal your choice, and aim for two thirds of the class average.</p>', unsafe_allow_html=True)
if demo:
    st.info('Demo mode — sample participants, simulated submissions, and both phases unlocked. Nothing is sent to the class API.')
elif commit_open:
    st.success('Commit phase is open · Submit before 15 November 2026, 23:59:59 Paris time.')
else:
    st.info('Reveal phase is open · The commit window is closed. Reveal the exact number and nonce you committed.')


def load_snapshot():
    if demo:
        commits, reveals = st.session_state.demo_commits, st.session_state.demo_reveals
    else:
        commits, reveals = fetch_table(api, 'commits'), fetch_table(api, 'reveals')
    st.session_state.snapshot = {'commits': commits.copy(), 'reveals': reveals.copy(),
                                 'loaded_at': datetime.now(timezone.utc).isoformat()}


def send(payload):
    if demo:
        row = {k: v for k, v in payload.items() if k != 'kind'}
        row['timestamp_utc'] = datetime.now(timezone.utc).isoformat()
        collection = st.session_state.demo_commits if payload['kind'] == 'commit' else st.session_state.demo_reveals
        collection.append(row)
        st.session_state.pop('snapshot', None)
        return 'confirmed'
    result = submit(api, payload)  # Rechecks the phase at submission time.
    st.session_state.pop('snapshot', None)
    return result


commit_tab, reveal_tab, leaderboard_tab = st.tabs(['01  Commit', '02  Reveal', '03  Leaderboard'])
with commit_tab:
    left, right = st.columns([1.4, 1], gap='large')
    with left:
        st.subheader('Seal your prediction')
        st.write('Choose your number and a private nonce. Keep both safe: you will need exactly the same values to reveal.')
        if not commit_open:
            st.warning('Commit window closed. Switch to Reveal, or enable Demo mode to explore this form.')
        if 'commit_nonce' not in st.session_state:
            st.session_state.commit_nonce = secrets.token_urlsafe(24)
        if st.button('Generate a new nonce', disabled=not commit_open):
            st.session_state.commit_nonce = secrets.token_urlsafe(24)
        with st.form('commit_form'):
            uid = st.text_input('University ID', placeholder='e.g. 20260001', key='commit_uid', disabled=not commit_open)
            number = st.number_input('Your number', 0, 100, 33, 1, key='commit_number', disabled=not commit_open)
            nonce = st.text_input('Secret nonce', type='password', key='commit_nonce', disabled=not commit_open,
                                  help='A random secret makes your number harder to guess. Save it before leaving.')
            saved = st.checkbox('I will download and keep my reveal receipt.', disabled=not commit_open)
            commit_clicked = st.form_submit_button('Commit my number', type='primary', disabled=not commit_open, use_container_width=True)
        if commit_clicked:
            try:
                uid, number, nonce = validate(uid, number, nonce)
                if not saved:
                    raise ValueError('Confirm that you will keep your reveal receipt.')
                digest = commitment(uid, number, nonce)
                # Retain the secret locally even if the network response is lost.
                st.session_state.receipt = {'university_id': uid, 'number': number, 'nonce': nonce,
                                            'commit': digest, 'mode': 'demo' if demo else 'live',
                                            'status': 'prepared; acceptance not yet confirmed'}
                with st.spinner('Submitting your commitment…'):
                    status = send({'kind': 'commit', 'uni_id': uid, 'commit': digest})
                st.session_state.receipt['status'] = status
                st.session_state.notice = status
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.warning('The submission could not be confirmed. It may already be recorded. Check the public commit ledger before retrying. Your prepared receipt is kept below.')
        receipt = st.session_state.get('receipt')
        if receipt:
            if receipt['status'] == 'confirmed':
                st.success('Demo commitment recorded.' if demo else 'The server acknowledged your commitment.')
            else:
                st.warning('Acceptance is unconfirmed. Keep this receipt and check the commit ledger before retrying.')
            st.caption('Your commitment hash')
            st.code(receipt['commit'], language=None)
            st.download_button('Download reveal receipt', json.dumps(receipt, indent=2), 'beauty_contest_receipt.json', 'application/json', use_container_width=True)
            st.caption('This receipt contains your secret nonce. Store it privately. It is available only in this browser session until you download it.')
    with right:
        with st.container(border=True):
            st.markdown('### A proof, without the answer')
            st.write('Your commitment is a fingerprint of your University ID, number and nonce.')
            st.code('SHA256(ID | number | nonce)', language=None)
            st.write('Only the fingerprint and your ID are submitted now. At reveal time, everyone can check that your answer matches it.')
            st.caption('Multiple attempts are allowed. The latest commit at or before your latest reveal is the one used for verification.')

with reveal_tab:
    left, right = st.columns([1.4, 1], gap='large')
    with left:
        st.subheader('Open your commitment')
        st.write('Enter exactly the same University ID, number and nonce you used when committing.')
        st.caption('Leaderboard eligibility: reveals recorded on ' + LEADERBOARD_WINDOW_LABEL + '.')
        if not reveal_open:
            st.warning('The reveal window is not open yet.')
        with st.form('reveal_form'):
            ruid = st.text_input('University ID', key='reveal_uid', placeholder='e.g. 20260001', disabled=not reveal_open)
            rnumber = st.number_input('Your committed number', 0, 100, 33, 1, key='reveal_number', disabled=not reveal_open)
            rnonce = st.text_input('Your original nonce', type='password', key='reveal_nonce', disabled=not reveal_open)
            consent = st.checkbox('I understand that my number and nonce will be public.', disabled=not reveal_open)
            reveal_clicked = st.form_submit_button('Verify & reveal', type='primary', disabled=not reveal_open, use_container_width=True)
        if reveal_clicked:
            try:
                ruid, rnumber, rnonce = validate(ruid, rnumber, rnonce)
                if not consent:
                    raise ValueError('Confirm that your reveal will be public.')
                # Fetch fresh commits: never validate against a cached leaderboard.
                with st.spinner('Checking your commitment…'):
                    commits = st.session_state.demo_commits if demo else fetch_table(api, 'commits')
                    cutoff = datetime.now(timezone.utc).isoformat()
                    check = consensus(commits, [{'uni_id': ruid, 'number': str(rnumber), 'nonce': rnonce, 'timestamp_utc': cutoff}])
                    if not check['rows'] or check['rows'][0]['Status'] != 'Verified':
                        reason = check['rows'][0]['Status'] if check['rows'] else 'Missing or invalid commitment'
                        raise ValueError(reason + '. Check your ID, number and original nonce before revealing.')
                with st.spinner('Submitting your reveal…'):
                    status = send({'kind': 'reveal', 'uni_id': ruid, 'number': rnumber, 'nonce': rnonce})
                if status == 'confirmed':
                    st.success('Demo reveal recorded.' if demo else 'Commitment matched locally. The server acknowledged your reveal. Refresh the leaderboard to verify the recorded result.')
                else:
                    st.warning('The server response did not confirm acceptance. Refresh the leaderboard before trying again.')
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.warning('The reveal could not be confirmed. Refresh the leaderboard before retrying: a submission may already have been recorded.')
    with right:
        with st.container(border=True):
            st.markdown('### Same inputs. Same hash.')
            st.write('We check your inputs against the latest public commit before sending your reveal.')
            st.write('Once recorded, your latest reveal is matched with the latest commit at or before its server timestamp.')
            st.caption('This check catches typing errors. The shared ledger remains the source used to calculate results.')

with leaderboard_tab:
    title, action = st.columns([3, 1])
    title.subheader('The class, in consensus')
    refresh = action.button('Refresh leaderboard', use_container_width=True)
    st.caption('Target = ⅔ × average of verified numbers. The smallest absolute distance wins; ties share the rank.')
    st.info('Only reveals submitted on ' + LEADERBOARD_WINDOW_LABEL + ' are included. The latest reveal within this window counts for each student.')
    if refresh or (demo and 'snapshot' not in st.session_state):
        try:
            with st.spinner('Reading both ledgers and verifying hashes…'):
                load_snapshot()
        except Exception as exc:
            if isinstance(exc, ValueError):
                st.error(str(exc))
            else:
                st.error('The API could not be read. Check your internet connection and the Apps Script deployment access, then refresh.')
            if 'snapshot' in st.session_state:
                st.warning('Showing the last successful snapshot. The data below may be outdated.')
    snapshot = st.session_state.get('snapshot')
    if not snapshot:
        st.info('Click Refresh leaderboard to read the public ledgers, verify reveals and calculate the ranking.')
    else:
        eligible_reveals = filter_leaderboard_reveals(snapshot['reveals'])
        result = leaderboard_consensus(snapshot['commits'], snapshot['reveals'])
        st.caption(f"{len(eligible_reveals)} of {len(snapshot['reveals'])} reveal entries fall within the leaderboard window.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric('Verified players', result['count'])
        c2.metric('Class average', '—' if result['average'] is None else f"{result['average']:.3f}")
        c3.metric('Target · ⅔ average', '—' if result['target'] is None else f"{result['target']:.3f}")
        c4.metric('Commit entries', len(snapshot['commits']))
        st.caption('Snapshot: ' + snapshot['loaded_at'] + ' · Results are provisional while new reveals are still being submitted.')
        if result['winners']:
            st.success('Leading now: ' + ', '.join(result['winners']))
        else:
            st.info('No verified reveals within the selected window. Only matching reveals recorded on ' + LEADERBOARD_WINDOW_LABEL + ' count.')
        if result['count']:
            st.subheader('Top 3')
            st.caption('Verified players only. Tied players share the same medal and rank.')
            podium_columns = st.columns(3)
            for rank, medal, place, column in zip(
                    (1, 2, 3), ('🥇', '🥈', '🥉'),
                    ('1st place', '2nd place', '3rd place'), podium_columns):
                with column:
                    with st.container(border=True):
                        st.subheader(f'{medal} {place}')
                        players = [row for row in result['rows']
                                   if row['Status'] == 'Verified' and row['Rank'] == rank]
                        for player in players:
                            st.text(player['University ID'])
                            st.metric('Chosen number', player['Number'])
                        if not players:
                            st.caption('No player at this rank yet.')
        if result['rows']:
            display = pd.DataFrame(result['rows'])[['Rank', 'University ID', 'Number', 'Distance', 'Status', 'Revealed at (UTC)']]
            display['Rank'] = display['Rank'].astype('Int64')
            display['Number'] = display['Number'].astype('Int64')
            st.dataframe(display, hide_index=True, use_container_width=True,
                         column_config={'Distance': st.column_config.NumberColumn(format='%.6f')})
        if result['issues']:
            st.warning(f"{len(result['issues'])} malformed ledger rows were excluded because their ID or timezone-aware timestamp was missing.")
            with st.expander('Data quality details'):
                st.dataframe(result['issues'], hide_index=True, use_container_width=True)
        summary = '\n'.join(['BEAUTY CONTEST — CLASS RESULTS', 'Rule: latest reveal + latest prior commit',
                              'Eligible reveals: ' + LEADERBOARD_WINDOW_LABEL,
                              f"Verified players: {result['count']}", f"Class average: {result['average']}",
                              f"Target (2/3 average): {result['target']}", 'Leaders: ' + ', '.join(result['winners']),
                              'Provisional snapshot: ' + snapshot['loaded_at']])
        d1, d2 = st.columns(2)
        d1.download_button('Download leaderboard CSV', csv_bytes(result['rows']), 'class_leaderboard.csv', 'text/csv', use_container_width=True)
        d2.download_button('Download results TXT', summary, 'class_results.txt', 'text/plain', use_container_width=True)
        with st.expander('Public commitment ledger'):
            st.caption('All commitment attempts. Hashes do not expose the chosen numbers.')
            st.dataframe(pd.DataFrame(snapshot['commits'], columns=['timestamp_utc', 'uni_id', 'commit']), hide_index=True, use_container_width=True)
            st.download_button('Download commits CSV', csv_bytes(snapshot['commits'], ['timestamp_utc', 'uni_id', 'commit']), 'merged_commits.csv', 'text/csv')
        with st.expander('Reveal ledger · eligible time window'):
            st.caption('Reveal attempts within the leaderboard window. Nonces in this ledger were intentionally made public by their participants.')
            st.dataframe(pd.DataFrame(eligible_reveals, columns=['timestamp_utc', 'uni_id', 'number', 'nonce']), hide_index=True, use_container_width=True)
            st.download_button('Download reveals CSV', csv_bytes(eligible_reveals, ['timestamp_utc', 'uni_id', 'number', 'nonce']), 'merged_reveals.csv', 'text/csv')

st.divider()
st.caption('NEOMA · Fintech & DeFi · Commit → Reveal → Verify · SHA-256 / append-only ledger')
