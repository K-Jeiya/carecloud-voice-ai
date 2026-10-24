# CareCloud Voice AI - Patient Registration (Demo)

A phone-based AI intake agent ("Riley") that registers patients through natural conversation, saves them
to a persistent database, and exposes them through a REST API and a Streamlit dashboard.

> **Demonstration only.** Synthetic data only. Not HIPAA compliant, not a production healthcare system.

## Status: what is verified vs. what you must do

| Item | Status |
|---|---|
| REST API, validation, soft delete, filters, pagination, error envelopes | Implemented; **66 automated tests pass** |
| Vapi webhook (tool calls, duplicate detection, update flow, failed-write handling, end-of-call report) | Implemented; tested with simulated Vapi payloads |
| Persistence across server restart (SQLite file) | Verified locally with a real uvicorn restart |
| Streamlit dashboard | Written; syntax-checked, **not exercised against a live API here** - run it once locally |
| Vapi account, assistant, US phone number | **You must create** (steps below). Nothing is provisioned by this repo |
| Public deployment URL | **You must deploy.** No live URL exists until you do |
| Real phone call quality | **Untested** until you place calls; tune the prompt in `app/prompts/patient_registration.txt` |

## Architecture

```
Caller --PSTN--> Vapi (phone number + STT + LLM + TTS)
                    | tool calls (HTTPS POST, X-Vapi-Secret)      end-of-call-report
                    v                                                  v
        FastAPI  /voice/webhook  ->  voice_provider.py (tool handlers)
                                           |  (shared service layer, no HTTP hop)
Dashboard (Streamlit) --REST--> /patients -> patient_service.py -> crud.py -> SQLite / PostgreSQL
```

* `app/integrations/voice_provider.py` - Vapi-specific code only (prompt loading, tool schemas, webhook parsing).
* `app/services/patient_service.py` - business rules, shared by the REST API and the voice tools.
* `app/crud.py` - data access. `app/validators.py` - **single source of truth for validation**.
* **The LLM never validates.** It calls `validate_patient_fields`; the backend decides what is valid and
  tells the LLM which fields to re-ask. `register_patient` re-validates everything with Pydantic.

### Voice tools (defined in `voice_provider.py`)
| Tool | Purpose |
|---|---|
| `lookup_patient_by_phone` | Duplicate detection - offer update instead of a duplicate |
| `validate_patient_fields` | Normalizes + validates fields collected so far; returns errors / missing fields |
| `register_patient` | Creates the record; rejected unless `caller_confirmed=true` |
| `update_existing_patient` | Partial update of an existing record, also requires confirmation |

Hang-up is handled by Vapi's built-in "End Call" function (enable it in the assistant's Tools).

## Tech stack and why
Python 3.12 + FastAPI (fast, typed, free Swagger) - SQLAlchemy 2 (works with SQLite and PostgreSQL) -
Pydantic v2 - SQLite locally, PostgreSQL in production - Streamlit (dashboard in one file) - pytest -
**Vapi** (handles telephony/STT/TTS so the time goes into prompt + backend, as the assessment suggests).

## Prerequisites
Python 3.12, Git. For the live system: a Vapi account, a hosting account (Render / Fly.io / Railway),
and a PostgreSQL URL if you host where disks are ephemeral.

## Local setup (Windows 11 PowerShell)
```powershell
git clone <YOUR_REPO_URL> carecloud-voice-ai
cd carecloud-voice-ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
Copy-Item .env.example .env           # then edit .env
python -m pytest -q                   # expect: 66 passed
python -m app.seed                    # optional: 2 clearly labelled SYNTHETIC patients (creates tables too)
uvicorn app.main:app --reload --port 8000
```
Swagger UI: <http://localhost:8000/docs> - Health: <http://localhost:8000/health>

Dashboard (second terminal, venv active):
```powershell
$env:API_BASE_URL = "http://localhost:8000"
streamlit run dashboard/app.py        # http://localhost:8501
```

## Environment variables
| Variable | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | API | default `sqlite:///./data/patients.db`; PostgreSQL URL for production |
| `SEED_DEMO_DATA` | API | `true` loads 2 synthetic patients at startup (idempotent) |
| `API_KEY` | API | optional; if set, `/patients*` need header `X-API-Key` |
| `VAPI_SERVER_SECRET` | API | must equal the secret configured in Vapi; webhook returns 401 otherwise |
| `PUBLIC_BASE_URL` | config printer | only for `python -m app.integrations.voice_provider` |
| `LOG_LEVEL` | API | default `INFO` |
| `API_BASE_URL`, `DASHBOARD_API_KEY` | Dashboard | API location / key (use Streamlit secrets or env, never code) |

No LLM or Vapi API key is needed by this backend: Vapi runs the LLM and calls us. Anything billed to
the LLM is configured inside your Vapi account.

## Database and persistence
Tables are created automatically on startup (`create_all`, never drops data). Constraints live in the DB
(`CHECK` on sex/lengths) and in Pydantic. Phones are stored as 10 digits, states upper-case, soft delete
uses `deleted_at`. A `call_logs` table stores each call's summary/transcript linked to the patient.
* **SQLite** survives restarts only if the file is on a persistent volume (Fly volume `/app/data`, Railway volume).
* **PostgreSQL** (Neon, Supabase, Railway, Render Postgres) persists independently of the web service - the safest choice.

## Deployment (pick one)
Pricing and free tiers change - **check each provider's current pricing page**; some require a card.

**Option A - Render (API) + Neon/Supabase (PostgreSQL).**
1. Create a free PostgreSQL database; copy its connection string.
2. Push the repo to GitHub. Render -> New -> Blueprint (uses `render.yaml`) or New Web Service -> Docker.
3. Set env vars: `DATABASE_URL`, `VAPI_SERVER_SECRET` (long random string), optionally `API_KEY`.
4. Confirm `https://<service>.onrender.com/health` returns ok.
5. Caveat: free Render instances sleep when idle, so the first call after a quiet period may be slow and
   Vapi's tool call may time out. Before the review, hit `/health` repeatedly (or use a free uptime
   pinger every 5 minutes) or use a paid always-on instance.

**Option B - Fly.io (SQLite on a volume, always-on).**
```powershell
fly auth login
fly launch --no-deploy --copy-config        # edit app name in fly.toml first
fly volume create patient_data --size 1 --region iad
fly secrets set VAPI_SERVER_SECRET=<random> 
fly deploy
```
Run `fly config validate` if the TOML complains (field names occasionally change between flyctl versions).

**Option C - Local + ngrok (acceptable per the assessment).** `ngrok http 8000`, use the https URL as the
webhook base. Your computer must stay on during review.

**Dashboard:** Streamlit Community Cloud -> new app from the repo, main file `dashboard/app.py`, secrets:
```toml
API_BASE_URL = "https://<your-api-host>"
DASHBOARD_API_KEY = ""   # only if API_KEY is set on the API
```
(or deploy as a second Render service with start command `streamlit run dashboard/app.py --server.port $PORT --server.address 0.0.0.0`).

## Vapi + phone number setup (dashboard clicks; verify labels in the current UI)
Run `python -m app.integrations.voice_provider` (with `PUBLIC_BASE_URL` set) to print the exact prompt,
first message, server URL and each tool's JSON schema for copy/paste.

1. **Assistant** -> Create. Model: pick a fast tool-capable model (e.g. OpenAI GPT-4o / 4o-mini). Paste the
   **system prompt** from `app/prompts/patient_registration.txt` and the **first message** printed by the script.
   (The prompt uses Vapi's `{{"now" | date: ...}}` variable; if your Vapi version does not render it,
   delete that sentence - the backend validates dates anyway.)
2. **Tools** -> Create Tool -> type *Function*, once per tool (four tools). Name, description and
   Parameters JSON come from the script output. Server URL: `https://<api-host>/voice/webhook`.
   Also add Vapi's built-in **End Call** tool to the assistant. Attach all to the assistant.
3. **Server URL secret:** in the assistant's Advanced/Server settings set Server URL to the same
   `/voice/webhook` and the secret equal to `VAPI_SERVER_SECRET`; make sure the server messages include
   **tool-calls** and **end-of-call-report**. Check a first call in Vapi's logs: if the webhook returns
   401, inspect which header carries the secret (the API accepts `X-Vapi-Secret` or `Authorization: Bearer`).
4. **Phone number** -> Create/Buy. Vapi has offered free US numbers (availability, limits and any card
   requirement depend on your account - confirm in the dashboard). Assign the assistant to the number for inbound calls.
   Fallback within Vapi: import a Twilio number (Twilio trial accounts may play a trial message and restrict callers).
5. Call the number. Watch your API logs: you should see `call=... tool=validate_patient_fields ...`.
6. Optional Spanish: choose a multilingual transcriber/voice in Vapi; the prompt already switches language.

**Fallback if no US number can be provisioned:** use Vapi's web "Talk to assistant" button, record a short
screen capture, and document in the submission what you tried and the blocker (the assessment explicitly allows this).

## API examples
```bash
curl -X POST $BASE/patients -H "Content-Type: application/json" -d '{
 "first_name":"Jane","last_name":"Synthetic","date_of_birth":"03/04/1990","sex":"Female",
 "phone_number":"(202) 555-0101","address_line_1":"100 Demo Street","city":"Springfield",
 "state":"IL","zip_code":"62701"}'
```
201 ->
```json
{"data":{"patient_id":"7c1f...","first_name":"Jane","last_name":"Synthetic","date_of_birth":"1990-03-04",
 "sex":"Female","phone_number":"2025550101","email":null,"state":"IL","preferred_language":"English",
 "created_at":"2026-10-24T12:00:00Z","updated_at":"2026-10-24T12:00:00Z","deleted_at":null},"error":null}
```
```bash
curl "$BASE/patients?last_name=synth&date_of_birth=03/04/1990&phone_number=2025550101&limit=20&offset=0"
curl $BASE/patients/<uuid>
curl -X PUT $BASE/patients/<uuid> -H "Content-Type: application/json" -d '{"city":"Chicago"}'
curl -X DELETE $BASE/patients/<uuid>
```
Error example (422): `{"data":null,"error":{"code":"validation_error","message":"Validation failed - phone_number: phone number must be a valid US 10-digit phone number (got 3 digits)","details":[{"field":"phone_number","message":"..."}]}}`.
Statuses: 200, 201, 400 (bad UUID/filter/malformed JSON/empty update), 401 (only if keys configured), 404, 422, 500, 503 (`/health`).
Add `-H "X-API-Key: ..."` if `API_KEY` is set.

## Demo call scenarios / test checklist
Use fake data only (e.g. Jane Synthetic, 202-555-01xx).
- [ ] **Happy path:** register with all required fields, decline optional, confirm -> "You're all set, Jane." -> call ends.
- [ ] **Optional fields:** accept insurance + emergency contact + language, verify they appear in the dashboard.
- [ ] **Out-of-order answers:** give address and phone before DOB; agent does not re-ask known items.
- [ ] **Correction:** "Actually my last name is D-A-V-I-S" -> only that field changes; re-read-back is correct.
- [ ] **Invalid DOB:** give a future date -> agent re-asks only DOB.
- [ ] **Invalid phone:** "123" -> agent re-asks only phone. Also try an invalid state ("XX") and ZIP ("123").
- [ ] **Restart:** say "let's start over" mid-call -> earlier values are discarded.
- [ ] **No confirmation:** answer "no, the city is wrong" at read-back -> fix, read back again; nothing saved before a clear yes.
- [ ] **Duplicate:** call again with the same phone -> agent offers to update; change city; verify only city changed.
- [ ] **Failed write:** (staging only) set `DATABASE_URL` to an unreachable/read-only DB or stop the API; agent apologizes, never claims success.
- [ ] **Hang up mid-call:** nothing is saved; log shows "ended WITHOUT a saved registration".
- [ ] **Persistence:** after call 1, `GET /patients` shows the record; redeploy/restart; call 2 still finds it (agent recognizes the phone).

Persistence check (PowerShell): `Invoke-RestMethod "$env:BASE/patients?last_name=Synthetic"` before and after restarting the service.

## Prompt engineering notes
The system prompt (`app/prompts/patient_registration.txt`, commented by section) defines: persona, short
spoken sentences, demo disclaimer, one-question-at-a-time, accept out-of-order answers, tool discipline
("backend is the authority"), duplicate flow, correction/interruption/restart rules, mandatory read-back,
and failure scripts (retry once, never fake success). Tool responses include an `instruction` field that
steers the LLM's next utterance.

## Security considerations
Secrets only via env vars; `.env` and databases are git-ignored; webhook secret compared in constant time;
inputs sanitized (control chars and `<>` stripped, length limits, `extra="forbid"`); parameterized SQL via
SQLAlchemy; 500s never expose stack traces; logs mask names, DOB, phones, email, street address and member ID.
**Not production-grade:** no HIPAA controls, no encryption at rest beyond what your DB host provides, the REST API is
open unless `API_KEY` is set, and `lookup_patient_by_phone` reveals a name to anyone who knows a phone number
(required by the assessment's bonus flow, acceptable only with synthetic data). Transcripts are stored in plain text.

## Known limitations / trade-offs
* Duplicate detection is by phone only; `POST /patients` itself allows shared phones (families), while the voice flow blocks silent duplicates.
* Voice updates cannot clear optional fields; use the API/dashboard for that.
* If the caller hangs up before confirmation, nothing is saved (by design).
* No auth on the dashboard itself; no rate limiting; SQLite = single instance only.
* Vapi's request/response format was taken from its current docs (`toolCallList`, `{"results":[{"toolCallId","result"}]}`);
  the secret header name and some dashboard labels should be re-checked against your account.
* Name validation allows letters, spaces, hyphens, apostrophes only (no periods/suffixes like "Jr.").

## Next steps
Appointment scheduling mock tool, Alembic migrations, API auth for the dashboard, rate limiting, retry/backoff
metrics, call-quality evals with scripted test callers, Spanish voice tuning, PostgreSQL by default.

## Git (safe publish)
```powershell
git init -b main
git status                      # confirm .env and data/*.db are NOT listed
git add .
git commit -m "Voice AI patient registration demo"
git remote add origin https://github.com/<you>/carecloud-voice-ai.git
git push -u origin main
```
If you ever committed a secret: rotate it first, then rewrite history - deleting the file is not enough.

## Submission checklist
- [ ] Repo URL (public, or private with reviewer access granted)
- [ ] US phone number tested end-to-end (all checklist items above)
- [ ] API base URL, `/health` OK, `/docs` reachable
- [ ] Dashboard URL loads and shows the call-created record
- [ ] README placeholders replaced (numbers, URLs), no secrets in Git history
- [ ] Any test credentials (`API_KEY`) included in the email
- [ ] If no number: documentation of attempts + local run instructions + recording

## Submission email template
```
Subject: Voice AI Patient Registration Assessment - <Your Name>

Dear Muhammad / CareCloud Team,

Please find my submission for the Voice AI Agent take-home assessment.

Repository:      <https://github.com/you/carecloud-voice-ai>
Phone number:    <+1 XXX XXX XXXX>   (US, answered by "Riley")
API base URL:    <https://your-api.example.com>   (Swagger: <base>/docs, health: <base>/health)
Dashboard:       <https://your-dashboard.streamlit.app>
Credentials:     <API key if enabled, otherwise "none required">

Testing notes:
- Please use synthetic data only; the agent states this is a demonstration.
- Call, register, confirm; the record appears in the dashboard and GET /patients.
- Call again with the same phone number to see duplicate detection / update flow.
- Stack: Vapi + FastAPI + SQLAlchemy + <PostgreSQL|SQLite volume> + Streamlit. Known limitations
  and next steps are listed in the README.
- <If hosting is on a free tier: the first request may take ~30-60s to wake the server.>

Thank you for your time,
<Your Name>
```
