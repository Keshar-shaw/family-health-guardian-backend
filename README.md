# Family Health Guardian - Backend API

“One Family. One Health Center. One Trusted Guardian.”

## Overview
Secure, consent-based family healthcare backend powered by FastAPI, Supabase PostgreSQL, Supabase Auth + JWT, and PostgreSQL RLS + RBAC.

## Phase 1 Features Implemented
- FastAPI server setup & CORS configuration
- Supabase PostgreSQL client integration
- JWT authentication middleware & user context extraction
- Profile management APIs (`/profiles/me`)
- Family & member management APIs with RBAC (`/families`)
- Consent-based access control APIs (`/consents`)
- PostgreSQL database migrations with Row-Level Security (RLS) policies
- Automated unit & API endpoint tests with pytest

## Setup & Running Locally

1. Create a virtual environment and install dependencies:
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Unix:
source .venv/bin/activate

pip install -r requirements.txt
```

2. Configure environment variables:
```bash
cp .env.example .env
```
Fill in your Supabase credentials in `.env`.

3. Run PostgreSQL Migration in Supabase SQL Editor:
Execute `migrations/01_phase1_schema.sql` in your Supabase project SQL editor.

4. Start the Development Server:
```bash
uvicorn app.main:app --reload --port 8000
```
Interactive API docs are available at `http://127.0.0.1:8000/docs`.

5. Run Tests:
```bash
pytest
```
