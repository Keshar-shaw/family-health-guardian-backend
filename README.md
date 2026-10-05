# Family Health Guardian - Backend API

> “One Family. One Health Center. One Trusted Guardian.”

## Overview
Family Health Guardian is an enterprise-grade, consent-driven family healthcare backend platform built with **FastAPI**, **Supabase PostgreSQL**, **Supabase Auth + JWT**, and hardened **PostgreSQL Row Level Security (RLS)** with **Role-Based Access Control (RBAC)**.

---

## Architecture & Security Principles

1. **Security Identity (`auth.uid()`)**: Security checks exclusively use authenticated user IDs (`sub` / `auth.uid()`), never client-supplied emails or untrusted claims.
2. **Zero-Trust Client Inputs**: Client-supplied `family_member_id` is always verified against caller ownership or active, non-expired family consent.
3. **Dual-Layer Authorization**: Enforced both at the **Backend Application Layer** (FastAPI dependencies and service checks) and at the **Database Engine Layer** (PostgreSQL Row-Level Security policies).
4. **Consent-Based Access**: Granular `READ_ONLY` and `FULL_ACCESS` consent delegations within families.
5. **Private Medical Storage**: Medical report binaries are stored exclusively in private Supabase Storage buckets with short-lived signed URLs, never stored as raw blobs in PostgreSQL.
6. **Immutable Audit Trail**: Append-only audit logs with automatic recursive secret sanitization and a database trigger preventing `UPDATE` and `DELETE` operations.

---

## Implemented Core Backend Modules (14/14)

1. **Authentication**: Supabase JWT authentication, token validation, user context extraction, profile management (`/profiles/me`).
2. **Family Members**: Family workspaces, role hierarchy (`ADMIN`, `MEMBER`), membership invitation and management (`/families`).
3. **Health Records**: Core medical profiles, blood group, allergies, chronic conditions, emergency notes with full CRUD and audit tracking (`/health-records`).
4. **Medical Reports**: Secure metadata management and private Supabase Storage for PDFs/images with timed pre-signed URLs (`/medical-reports`).
5. **Medicines**: Prescription tracking, dosage, frequency, and active status filtering (`/medicines`).
6. **Medicine Schedule**: Intake schedules, reminder triggers, time-of-day regimens (`/medicine-schedules`).
7. **Medicine Logs**: Adherence tracking (`TAKEN`, `MISSED`, `SKIPPED`) with intake timestamps (`/medicine-logs`).
8. **Emergency Contacts**: Ranked primary and secondary emergency contacts with strict phone validation (`/emergency-contacts`).
9. **Emergency SOS**: Immediate distress broadcast system with real-time responder dispatch (`/emergency/sos`).
10. **SOS History**: Chronological, filtered incident history with date, member, and status filters (`/emergency/sos/history`).
11. **Location Support**: Optional GPS coordinate capture (`latitude`, `longitude`, `accuracy`, `timestamp`) with bounding validation without continuous background tracking.
12. **Permissions / RBAC / RLS**: Granular consent requests, approvals, revocations, and hardened PostgreSQL RLS functions (`/consents`).
13. **Notifications**: Extensible notification abstraction for medicine reminders and SOS alerts with feed and status management (`/notifications`).
14. **Audit Logs**: Tamper-evident, immutable audit trail with automatic secret sanitization across all sensitive healthcare operations (`/audit-logs`).

---

## Database Migrations

Apply the migrations in numerical order in your Supabase SQL Editor:

| Migration File | Description |
|---|---|
| `01_phase1_schema.sql` | `profiles`, `families`, `family_members`, `consents`, initial RLS helper functions |
| `02_health_records.sql` | `health_records` table, unique constraints, RLS policies, update triggers |
| `03_medicines.sql` | `medicines` table, indexing, RLS policies, update triggers |
| `04_medicine_schedules.sql` | `medicine_schedules` table, intake scheduling, RLS policies |
| `05_medicine_logs.sql` | `medicine_logs` table, adherence tracking, RLS policies |
| `06_emergency_contacts.sql` | `emergency_contacts` table, priority ordering, RLS policies |
| `07_emergency_sos.sql` | `sos_events` table, `sos_event_status` enum, RLS policies |
| `08_medical_reports.sql` | `medical_reports` table, private `medical-reports` Supabase Storage bucket & storage RLS policies |
| `09_authorization_audit.sql` | Unified cross-module authorization hardening, `can_read_health_record`, `can_write_health_record` |
| `10_notifications.sql` | `notifications` table, `notification_type` & `notification_status` enums, RLS policies |
| `11_sos_location_support.sql` | Optional GPS coordinates, validation check constraints, and spatial indexes on `sos_events` |
| `12_audit_logs.sql` | `audit_logs` table, immutability trigger `prevent_audit_log_modification`, append-only RLS |

---

## API Endpoints Reference

### Health & Profiles
- `GET /health` - Service health status
- `GET /profiles/me` - Retrieve current user profile
- `PUT /profiles/me` - Update current user profile

### Families & Members
- `POST /families` - Create new family workspace (creator assigned `ADMIN`)
- `GET /families` - List all families current user belongs to
- `GET /families/{family_id}` - Retrieve family details and member list
- `POST /families/{family_id}/members` - Add member to family (`ADMIN` required)
- `DELETE /families/{family_id}/members/{user_id}` - Remove family member

### Consents & Permissions
- `POST /consents` - Request or grant member access (`READ_ONLY` or `FULL_ACCESS`)
- `GET /consents` - List active and pending consents for caller
- `PATCH /consents/{consent_id}` - Approve, deny, or revoke consent

### Health Records
- `POST /health-records` - Create member health record
- `GET /health-records` - List authorized health records
- `GET /health-records/{id}` - Retrieve specific health record by ID
- `PUT /health-records/{id}` - Update health record (`FULL_ACCESS` consent required)
- `DELETE /health-records/{id}` - Delete health record (`FULL_ACCESS` consent required)

### Medicines & Prescriptions
- `POST /medicines` - Register new medicine
- `GET /medicines` - List medicines (filter by `family_member_id`, `is_active`)
- `GET /medicines/{id}` - Retrieve medicine details
- `PUT /medicines/{id}` - Update medicine
- `DELETE /medicines/{id}` - Delete medicine

### Medicine Schedules & Reminders
- `POST /medicine-schedules` - Create intake schedule (dispatches reminder notification if enabled)
- `GET /medicine-schedules` - List medicine schedules (filter by `medicine_id`)
- `GET /medicine-schedules/{id}` - Retrieve specific schedule
- `PUT /medicine-schedules/{id}` - Update schedule
- `DELETE /medicine-schedules/{id}` - Delete schedule

### Medicine Logs (Adherence)
- `POST /medicine-logs` - Log intake event (`TAKEN`, `MISSED`, `SKIPPED`)
- `GET /medicine-logs` - List intake logs (filter by `medicine_id`, `family_member_id`, date range)
- `GET /medicine-logs/{id}` - Retrieve specific intake log
- `PATCH /medicine-logs/{id}` - Update log status/notes
- `DELETE /medicine-logs/{id}` - Delete intake log

### Emergency Contacts
- `POST /emergency-contacts` - Add emergency contact with priority rank
- `GET /emergency-contacts` - List emergency contacts (filter by `family_member_id`)
- `GET /emergency-contacts/{id}` - Retrieve contact details
- `PUT /emergency-contacts/{id}` - Update contact details
- `DELETE /emergency-contacts/{id}` - Remove contact

### Emergency SOS & Location
- `POST /emergency/sos` - Trigger emergency SOS with optional GPS coordinates
- `GET /emergency/sos/history` - Chronological SOS history (newest first) with filters
- `GET /emergency/sos/{id}` - Retrieve SOS event details
- `PATCH /emergency/sos/{id}/status` - Update status (`ACKNOWLEDGED`, `RESOLVED`, `CANCELLED`)

### Medical Reports (Supabase Storage)
- `POST /medical-reports` - Upload medical report (PDF, PNG, JPG; validates size & MIME type)
- `GET /medical-reports` - List reports with secure pre-signed download URLs
- `GET /medical-reports/{id}` - Retrieve report metadata and fresh download URL
- `DELETE /medical-reports/{id}` - Delete metadata and purge file from Supabase Storage

### Notifications
- `GET /notifications` - Retrieve notification feed (filter by `status`, `type`, pagination)
- `PATCH /notifications/{id}/read` - Mark notification as `READ`

### Audit Trail
- `GET /audit-logs` - Query immutable audit logs (filter by `family_id`, `member_id`, `action`, `resource_type`)

---

## Environment Configuration

Create a `.env` file in the root backend directory:

```env
# Application Configuration
APP_NAME="Family Health Guardian API"
DEBUG=True
API_V1_STR="/api/v1"

# Supabase Configuration
SUPABASE_URL="https://your-supabase-project.supabase.co"
SUPABASE_KEY="your-supabase-anon-or-service-key"
SUPABASE_JWT_SECRET="your-supabase-jwt-secret-min-32-chars"
```

---

## Local Development & Testing

1. Activate virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate # Unix / macOS
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run test suite:
```bash
pytest
```

4. Start development server:
```bash
uvicorn app.main:app --reload --port 8000
```
Interactive OpenAPI documentation will be accessible at `http://127.0.0.1:8000/docs`.
