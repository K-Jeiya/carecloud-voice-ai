# CareCloud Voice AI – Patient Registration Demo

A demo patient-registration voice agent with a FastAPI backend, database-backed patient records, and a Streamlit dashboard.

> **Demo only:** Uses synthetic data. Not HIPAA-compliant or intended for production healthcare use.

## Live Demo

| Component | Link |
|---|---|
| GitHub Repository | [carecloud-voice-ai](https://github.com/K-Jeiya/carecloud-voice-ai) |
| Streamlit Dashboard | [Open Dashboard](https://carecloud-voice-ai.streamlit.app/) |
| API | [Open API](https://carecloud-voice-ai.hostless.app/) |
| Swagger Documentation | [Open Swagger UI](https://carecloud-voice-ai.hostless.app/docs) |
| Health Check | [Check API Health](https://carecloud-voice-ai.hostless.app/health) |

## Features

- Patient registration and record retrieval
- Patient update and soft-delete endpoints
- Patient search, input validation, and structured error responses
- Streamlit dashboard for patient management
- Vapi voice-agent integration and webhook handlers
- Duplicate-patient lookup and update flow in the voice workflow
- Call-log endpoint and database persistence

## Architecture

```text
Vapi Voice Agent
       |
       | Webhook / Tool Calls
       v
FastAPI Backend
       |
       v
Patient Service
       |
       v
SQLAlchemy Database
       ^
       |
Streamlit Dashboard
       |
       | REST API
       +-------------------->
