"""Streamlit dashboard. Talks ONLY to the REST API (no DB access, no secrets in code).

Config comes from environment variables or Streamlit secrets:
  API_BASE_URL       e.g. https://your-api.onrender.com   (default http://localhost:8000)
  DASHBOARD_API_KEY  only needed if the API has API_KEY set
"""
from __future__ import annotations
from datetime import datetime

import json
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv()

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests
import streamlit as st

TIMEOUT = 20
SEX_OPTIONS = ["Male", "Female", "Other", "Decline to Answer"]


def _setting(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file present
        pass
    return os.getenv(name, default)


API_BASE = _setting(
    "API_BASE_URL",
    "https://carecloud-voice-ai.hostless.app"
).rstrip("/")
API_KEY = _setting("DASHBOARD_API_KEY")


class ApiError(Exception):
    pass


def api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    try:
        resp = requests.request(method, f"{API_BASE}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.exceptions.Timeout:
        raise ApiError("The API took too long to respond. If it just woke up, wait a few seconds and refresh.")
    except requests.exceptions.ConnectionError:
        raise ApiError(f"Could not reach the API at {API_BASE}. Is it running?")
    try:
        body = resp.json()
    except ValueError:
        raise ApiError(f"Unexpected response from API (HTTP {resp.status_code}).")
    if resp.status_code >= 400 or body.get("error"):
        err = body.get("error") or {}
        raise ApiError(err.get("message") or f"API error (HTTP {resp.status_code}).")
    return body


@st.cache_data(ttl=10, show_spinner=False)
def fetch_patients(last_name: str, dob: str, phone: str, refresh_token: int) -> list[dict[str, Any]]:
    dob_api = ""
    if dob:
        try:
            dob_api = datetime.strptime(dob, "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            raise ApiError("Enter DOB in MM/DD/YYYY format, e.g. 01/04/1990.")

    params = {
        k: v
        for k, v in {
            "last_name": last_name,
            "date_of_birth": dob_api,
            "phone_number": phone,
        }.items()
        if v
    }
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:  # page through everything (max 1000 rows for the demo)
        body = api("GET", "/patients", params={**params, "limit": 200, "offset": offset})
        rows.extend(body["data"])
        offset += 200
        if offset >= body["meta"]["total"] or offset >= 1000:
            return rows


def fmt_phone(p: str | None) -> str:
    return f"({p[:3]}) {p[3:6]}-{p[6:]}" if p and len(p) == 10 else (p or "")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


st.markdown("""<style>
input::placeholder {
    color: #9ca3af !important;
    opacity: 1 !important;
}
</style>""", unsafe_allow_html=True)

st.set_page_config(page_title="Patient Registry (Demo)", page_icon="🩺", layout="wide")
st.title("🩺 Patient Registry")
st.warning("Demonstration system. Use SYNTHETIC data only - never enter real patient information.")


if "refresh" not in st.session_state:
    st.session_state.refresh = 0
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# ------------------------------------------------------------------ sidebar: refresh only
with st.sidebar:
    st.header("Controls")
    if st.button("Refresh", use_container_width=True):
        st.session_state.refresh += 1
        st.rerun()
    st.caption(f"API: {API_BASE}")

try:
    with st.spinner("Loading patients..."):
        if "applied_filters" not in st.session_state:
            st.session_state.applied_filters = {
                "last_name": "",
                "dob": "",
                "phone": "",
            }
        filters = st.session_state.applied_filters
        patients = fetch_patients("", "", "", st.session_state.refresh)
except ApiError as exc:
    st.error(str(exc))
    st.stop()

# ------------------------------------------------------------------ metrics
week_ago = datetime.now(timezone.utc) - timedelta(days=7)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Active patients (matching filters)", len(patients))
m2.metric("Registered last 7 days", sum(1 for p in patients if parse_dt(p["created_at"]) >= week_ago))
m3.metric("With insurance info", sum(1 for p in patients if p.get("insurance_provider")))
m4.metric("With emergency contact", sum(1 for p in patients if p.get("emergency_contact_name")))

tab_list, tab_form, tab_voice = st.tabs([
    "📋 Patients",
    "➕ Create / ✏️ Update",
    "🎙️ Voice Registration",
])

# ------------------------------------------------------------------ list + detail + delete
with tab_list:
    if not patients:
        st.info("No patients match. Register one by phone or use the Create tab.")
    else:
        df = pd.DataFrame(
            [{
                "Name": f"{p['first_name']} {p['last_name']}",
                "DOB": p["date_of_birth"],
                "Sex": p["sex"],
                "Phone": fmt_phone(p["phone_number"]),
                "City/State": f"{p['city']}, {p['state']}",
                "Language": p["preferred_language"],
                "Registered (UTC)": p["created_at"][:16].replace("T", " "),
            } for p in patients]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.subheader("Patient details")
        labels = {p["patient_id"]: f"{p['last_name']}, {p['first_name']} - {p['date_of_birth']}" for p in patients}
        chosen = st.selectbox("Select a patient", list(labels), format_func=lambda k: labels[k])
        sel = next(p for p in patients if p["patient_id"] == chosen)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Patient ID:** `{sel['patient_id']}`")
            st.markdown(f"**Name:** {sel['first_name']} {sel['last_name']}")
            st.markdown(f"**DOB / Sex:** {sel['date_of_birth']} / {sel['sex']}")
            st.markdown(f"**Phone:** {fmt_phone(sel['phone_number'])}")
            st.markdown(f"**Email:** {sel.get('email') or '-'}")
            st.markdown(f"**Language:** {sel['preferred_language']}")
        with c2:
            addr2 = f", {sel['address_line_2']}" if sel.get("address_line_2") else ""
            st.markdown(f"**Address:** {sel['address_line_1']}{addr2}, {sel['city']}, {sel['state']} {sel['zip_code']}")
            st.markdown(f"**Insurance:** {sel.get('insurance_provider') or '-'} / {sel.get('insurance_member_id') or '-'}")
            st.markdown(f"**Emergency contact:** {sel.get('emergency_contact_name') or '-'} {fmt_phone(sel.get('emergency_contact_phone'))}")
            st.markdown(f"**Created / Updated (UTC):** {sel['created_at'][:19]} / {sel['updated_at'][:19]}")

        with st.expander("Call summaries / transcripts"):
            try:
                calls = api("GET", f"/patients/{chosen}/calls")["data"]
                if not calls:
                    st.caption("No call recorded for this patient (created via API/dashboard).")
                for c in calls:
                    st.markdown(f"**{c['created_at'][:19]}** - {c.get('action') or ''} - {c.get('ended_reason') or ''}")
                    st.write(c.get("summary") or "_No summary yet._")
                    if c.get("transcript"):
                        st.text(c["transcript"])
            except ApiError as exc:
                st.error(str(exc))

        st.subheader("Soft-delete")
        confirm = st.checkbox(f"Yes, soft-delete {sel['first_name']} {sel['last_name']} (record is hidden, not erased)")
        if st.button("🗑️ Delete patient", disabled=not confirm, type="primary"):
            try:
                with st.spinner("Deleting..."):
                    api("DELETE", f"/patients/{chosen}")
                st.session_state.refresh += 1
                st.session_state.flash = "Patient soft-deleted."
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))

# ------------------------------------------------------------------ create / update form
with tab_form:
    mode = st.radio("Mode", ["Create new patient", "Update existing patient"], horizontal=True)
    existing: dict[str, Any] = {}
    target_id = None
    if mode == "Update existing patient":
        if not patients:
            st.info("No patients available to update.")
            st.stop()
        labels2 = {p["patient_id"]: f"{p['last_name']}, {p['first_name']} - {p['date_of_birth']}" for p in patients}
        target_id = st.selectbox("Patient to update", list(labels2), format_func=lambda k: labels2[k], key="upd_sel")
        existing = next(p for p in patients if p["patient_id"] == target_id)

    def v(key: str, default: str = "") -> str:
        return existing.get(key) or default

    with st.form(f"patient_form_{target_id or 'new'}"):
        st.caption("Required fields are marked with *")
        a, b = st.columns(2)
        first = a.text_input("First name *", v("first_name"))
        last = b.text_input("Last name *", v("last_name"))
        dob_default = date.fromisoformat(existing["date_of_birth"]) if existing else date(1990, 1, 1)
        dob = a.date_input("Date of birth *", dob_default, min_value=date(1900, 1, 1), max_value=date.today())
        sex = b.selectbox("Sex *", SEX_OPTIONS, index=SEX_OPTIONS.index(existing["sex"]) if existing else 0)
        phone = a.text_input("Phone number *", v("phone_number"))
        email = b.text_input("Email", v("email"))
        addr1 = a.text_input("Address line 1 *", v("address_line_1"))
        addr2 = b.text_input("Address line 2", v("address_line_2"))
        city = a.text_input("City *", v("city"))
        c3, c4 = b.columns(2)
        state = c3.text_input("State * (2 letters)", v("state"), max_chars=2)
        zipc = c4.text_input("ZIP *", v("zip_code"))
        ins = a.text_input("Insurance provider", v("insurance_provider"))
        mid = b.text_input("Insurance member ID", v("insurance_member_id"))
        lang = a.text_input("Preferred language", v("preferred_language", "English"))
        ecn = b.text_input("Emergency contact name", v("emergency_contact_name"))
        ecp = a.text_input("Emergency contact phone", v("emergency_contact_phone"))
        submitted = st.form_submit_button("Save", type="primary")

    if submitted:
        body = {
            "first_name": first, "last_name": last, "date_of_birth": dob.strftime("%m/%d/%Y"), "sex": sex,
            "phone_number": phone, "address_line_1": addr1, "city": city, "state": state, "zip_code": zipc,
            "email": email or None, "address_line_2": addr2 or None, "insurance_provider": ins or None,
            "insurance_member_id": mid or None, "preferred_language": lang or "English",
            "emergency_contact_name": ecn or None, "emergency_contact_phone": ecp or None,
        }
        try:
            with st.spinner("Saving..."):
                if target_id:
                    api("PUT", f"/patients/{target_id}", json=body)
                    st.session_state.flash = "Patient updated."
                else:
                    api("POST", "/patients", json=body)
                    st.session_state.flash = "Patient created."
            st.session_state.refresh += 1
            st.rerun()
        except ApiError as exc:
            st.error(str(exc))


# ------------------------------------------------------------------
# Voice registration — embedded inside Streamlit
with tab_voice:
    st.subheader("🎙️ CareCloud Voice Registration")
    st.write(
        "Register a demo patient by speaking with the CareCloud assistant. "
        "Use fictional details only."
    )

    vapi_public_key = _setting("VAPI_PUBLIC_KEY")
    vapi_assistant_id = _setting("VAPI_ASSISTANT_ID")

    if not vapi_public_key or not vapi_assistant_id:
        st.error(
            "Voice setup incomplete. Check VAPI_PUBLIC_KEY and "
            "VAPI_ASSISTANT_ID in your root .env file."
        )
    else:
        public_key_js = json.dumps(vapi_public_key)
        assistant_id_js = json.dumps(vapi_assistant_id)

        voice_html = f"""
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{
              font-family: Arial, sans-serif;
              color: #1f2937;
              padding: 12px;
            }}
            button {{
              border: 0;
              border-radius: 8px;
              padding: 12px 18px;
              margin-right: 8px;
              cursor: pointer;
              font-size: 15px;
            }}
            #start {{ background: #166534; color: white; }}
            #stop {{ background: #e5e7eb; color: #111827; }}
            #status {{
              margin-top: 18px;
              padding: 14px;
              background: #f3f4f6;
              border-radius: 8px;
            }}
          </style>
        </head>
        <body allow="microphone">
          <button id="start">🎙️ Start Voice Registration</button>
          <button id="stop" disabled>End Call</button>
          <div id="status">Ready. Click Start to begin.</div>

          <script type="module">
            import Vapi from
              "https://esm.sh/@vapi-ai/web";

            const vapi = new Vapi({public_key_js});
            const assistantId = {assistant_id_js};

            const start = document.getElementById("start");
            const stop = document.getElementById("stop");
            const status = document.getElementById("status");

            start.addEventListener("click", async () => {{
              start.disabled = true;
              status.textContent = "Connecting...";

              try {{
                await vapi.start(assistantId);
              }} catch (error) {{
                status.textContent =
                  "Could not connect. Check microphone permission and Vapi setup.";
                start.disabled = false;
              }}
            }});

            stop.addEventListener("click", () => vapi.stop());

            vapi.on("call-start", () => {{
              status.textContent =
                "Connected! Speak to the CareCloud assistant.";
              stop.disabled = false;
            }});

            vapi.on("call-end", () => {{
              status.textContent =
                "Call ended. Refresh the Patients tab to see new records.";
              start.disabled = false;
              stop.disabled = true;
            }});

            vapi.on("error", () => {{
              status.textContent =
                "Voice error. Check microphone permission and Vapi configuration.";
              start.disabled = false;
              stop.disabled = true;
            }});
          </script>
        </body>
        </html>
        """

        components.iframe(f"{API_BASE}/voice-ui", height=420, scrolling=False)

        st.info(
            "After the call ends, click Refresh in the sidebar to load "
            "the latest registration."
        )
