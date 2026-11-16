# Beauty Contest — Streamlit

An English classroom interface based on the supplied commit/reveal clients, consensus script and PRD. Connects to the Google Apps Script URL provided in `info.txt`.

## Run locally

Requires Python 3.10+.

```bash
git clone https://github.com/code-glitch-development/beauty-contest-streamlit.git
cd beauty-contest-streamlit
python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501. Enable **Demo mode** in the sidebar to test every phase without sending data to the API. Live mode is the default. No API requests are made until a participant submits a form or refreshes the leaderboard.

## Three tabs

- **Commit:** University ID, integer 0–100, random or custom secret nonce. Sends only `kind`, `uni_id`, `commit`. A downloadable JSON receipt preserves the exact number and nonce, including when submission acceptance is uncertain.
- **Reveal:** re-enter the original inputs. Checks the latest public commitment before sending `kind`, `uni_id`, `number`, `nonce`. Number and nonce become public.
- **Leaderboard:** reads both CSV ledgers, verifies commitments, displays verified and rejected attempts, shared ranks, current leaders, class average and target. Exports leaderboard CSV, results TXT and both public ledgers. Refresh is manual and results remain provisional while reveals continue.

## Dates and rules

Commit closes on **15 November 2026 at 23:59:59 Europe/Paris**. Reveal opens on **16 November 2026 at 00:00:00 Europe/Paris**. These reproduce the provided clients. On or after 16 November, a disabled live Commit form is expected. Demo mode unlocks both forms with an isolated session-only ledger.

The commitment is exactly `SHA256(uni_id|integer|nonce)` in UTF-8. IDs and nonces are trimmed as in the supplied clients. Nonces are never taken from `info.txt` or shared by default: each participant gets a random one.

Consensus takes each student's latest reveal and the latest commit at or before that reveal. Equal timestamps use the last CSV row. It does not fall back to an older matching commit or reveal. Out-of-range numbers, non-integers, missing nonces and hash mismatches are rejected. Malformed or timezone-naive timestamps are excluded and reported, rather than crashing or silently matching. Distances are sorted numerically; ties within 1e-12 share competition ranks. The target is two thirds of the verified class average.

As in the supplied merge script, consensus does not independently exclude late commits or early reveals: the API is responsible for enforcing the phase schedule. The local form checks are convenience checks and can be bypassed by other clients. For reuse with another cohort, update `DEADLINE` / `REVEAL_OPEN` in `game.py` and the displayed date copy in `app.py`.

## API and deployment

The supplied URL is the default. To change deployments, set `BEAUTY_API_URL` as an environment variable or add `.streamlit/secrets.toml`:

```toml
BEAUTY_API_URL = "https://script.google.com/macros/s/YOUR_DEPLOYMENT/exec"
```

The URL must be an HTTPS Apps Script deployment URL, without query parameters. The API must return public CSV for `GET ?table=commits` (`timestamp_utc,uni_id,commit`) and `GET ?table=reveals` (`timestamp_utc,uni_id,number,nonce`). It must accept JSON POSTs. An explicit JSON `ok: true`, `success: true` or `status: "ok"/"success"` acknowledges a submission; unknown responses are reported as unconfirmed. No automatic POST retries are performed. After an ambiguous error, inspect the ledger before retrying.

For Streamlit Community Cloud, select repository `code-glitch-development/beauty-contest-streamlit`, branch `main`, and main file `app.py`. Python 3.12 is recommended. Configure secrets only if you need to override the supplied API URL. No backend changes are included. The supplied backend has not been modified, and no live submissions were made during development.

Commit/reveal does not authenticate ownership of a University ID. This frontend preserves the classroom protocol; authentication, authoritative deadlines and duplicate-ID protection require backend support. The two CSV reads are a sequential snapshot, so refresh again after concurrent submissions settle.

## Verification

```bash
python -m unittest discover -s tests -v
```

Tests use local fixtures and mocked HTTP responses. Streamlit smoke tests use `streamlit.testing.v1.AppTest`; they exercise closed live Commit, demo commit/reveal and leaderboard without live API writes.

## Development validation in this delivery

17 protocol and mocked transport tests passed. The two Streamlit integration tests were included but skipped because Streamlit could not be installed in the build environment. Python compilation passed. The live API connection and browser rendering have not been verified here.
