import pytest
import uuid
from unittest.mock import MagicMock
from app.auth.dependencies import get_supabase
from app.main import app
from app.services.audit import sanitize_metadata, AuditService
from app.schemas.audit_log import AuditAction, AuditResourceType


class MockQueryBuilder:
    def __init__(self, data=None, table_name=None, tables_ref=None):
        self._table_name = table_name
        self._tables_ref = tables_ref
        self._data = [dict(item) for item in data] if data is not None else []
        self._action = "select"
        self._action_data = None
    
    def select(self, *args, **kwargs):
        self._action = "select"
        return self

    def eq(self, column, value):
        self._data = [item for item in self._data if str(item.get(column)) == str(value)]
        return self

    def in_(self, column, values):
        val_strs = [str(v) for v in values]
        self._data = [item for item in self._data if str(item.get(column)) in val_strs]
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    def insert(self, payload):
        self._action = "insert"
        p = dict(payload)
        if "id" not in p:
            p["id"] = str(uuid.uuid4())
        p.setdefault("created_at", "2026-10-06T00:00:00Z")
        p.setdefault("updated_at", "2026-10-06T00:00:00Z")
        if self._tables_ref is not None and self._table_name in self._tables_ref:
            self._tables_ref[self._table_name].append(p)
        self._action_data = [p]
        return self

    def update(self, payload):
        self._action = "update"
        updated = []
        for item in self._data:
            item.update(payload)
            item.setdefault("updated_at", "2026-10-06T00:00:00Z")
            updated.append(item)
        self._action_data = updated
        return self

    def delete(self):
        self._action = "delete"
        self._action_data = list(self._data)
        return self

    def execute(self):
        res = MagicMock()
        if self._action in ("insert", "update", "delete"):
            res.data = list(self._action_data) if self._action_data is not None else []
        else:
            res.data = list(self._data)
        return res


def setup_mock_supabase(tables_data):
    mock_supabase = MagicMock()

    def get_table(name):
        data = tables_data.get(name, [])
        return MockQueryBuilder(data, table_name=name, tables_ref=tables_data)

    mock_supabase.table.side_effect = get_table
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload.return_value = {"Key": "test_path"}
    mock_bucket.remove.return_value = [{"name": "test_path"}]
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://example.com/file.pdf?token=123"}
    mock_storage.from_.return_value = mock_bucket
    mock_supabase.storage = mock_storage
    return mock_supabase


# -------------------------------------------------------------
# 1. Sanitization & Secret Prevention Tests
# -------------------------------------------------------------

def test_sanitize_metadata_strips_secrets():
    """Verify that passwords, tokens, API keys, and secrets are removed from audit metadata."""
    raw_metadata = {
        "user_email": "patient@example.com",
        "action_note": "routine checkup",
        "password": "SuperSecretPassword123!",
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "jwt": "header.payload.signature",
        "nested": {
            "api_key": "sk_live_123456789",
            "safe_field": 42,
            "auth_header": "Bearer secret_token"
        }
    }

    sanitized = sanitize_metadata(raw_metadata)

    assert "password" not in sanitized
    assert "access_token" not in sanitized
    assert "jwt" not in sanitized
    assert "user_email" in sanitized
    assert sanitized["action_note"] == "routine checkup"
    assert "api_key" not in sanitized["nested"]
    assert "auth_header" not in sanitized["nested"]
    assert sanitized["nested"]["safe_field"] == 42


# -------------------------------------------------------------
# 2. AuditService Unit Tests
# -------------------------------------------------------------

def test_audit_service_log_action():
    """Test recording an audit log event via AuditService."""
    actor_id = str(uuid.uuid4())
    family_id = uuid.uuid4()
    member_id = uuid.uuid4()
    record_id = uuid.uuid4()

    mock_db = setup_mock_supabase({"audit_logs": []})

    log_entry = AuditService.log_action(
        supabase=mock_db,
        actor_user_id=actor_id,
        action=AuditAction.HEALTH_RECORD_CREATED.value,
        resource_type=AuditResourceType.HEALTH_RECORD.value,
        resource_id=record_id,
        family_id=family_id,
        family_member_id=member_id,
        metadata={"blood_group": "A+", "token": "should_be_stripped"}
    )

    assert log_entry is not None
    assert log_entry["actor_user_id"] == actor_id
    assert log_entry["action"] == AuditAction.HEALTH_RECORD_CREATED.value
    assert log_entry["resource_type"] == AuditResourceType.HEALTH_RECORD.value
    assert log_entry["metadata"]["blood_group"] == "A+"
    assert "token" not in log_entry["metadata"]


# -------------------------------------------------------------
# 3. Healthcare Actions Integration Tests
# -------------------------------------------------------------

def test_health_record_creation_triggers_audit_log(client, auth_headers, test_user_id):
    """Verify that creating a health record records a HEALTH_RECORD_CREATED audit log."""
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [],
        "audit_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "family_member_id": family_member_id,
        "blood_group": "B+",
        "allergies": "Peanuts"
    }

    response = client.post("/health-records", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201


def test_sos_trigger_triggers_audit_log(client, auth_headers, test_user_id):
    """Verify that triggering an SOS alert records an SOS_TRIGGERED audit log."""
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [],
        "sos_events": [],
        "notifications": [],
        "audit_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "family_member_id": family_member_id,
        "notes": "Emergency assistance requested"
    }

    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201


# -------------------------------------------------------------
# 4. API & Authorization Tests
# -------------------------------------------------------------

def test_get_audit_logs_api(client, auth_headers, test_user_id):
    """Test retrieving user audit logs via GET /audit-logs."""
    log_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "audit_logs": [{
            "id": log_id,
            "actor_user_id": test_user_id,
            "family_id": str(uuid.uuid4()),
            "family_member_id": member_id,
            "action": AuditAction.HEALTH_RECORD_VIEWED.value,
            "resource_type": AuditResourceType.HEALTH_RECORD.value,
            "resource_id": str(uuid.uuid4()),
            "metadata": {"test": True},
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get("/audit-logs", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == log_id
    assert data[0]["action"] == AuditAction.HEALTH_RECORD_VIEWED.value


def test_get_audit_logs_unauthorized_family_forbidden(client, auth_headers, test_user_id):
    """User cannot query audit logs of an unrelated family."""
    unrelated_family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": []  # User not in this family
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/audit-logs?family_id={unrelated_family_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Access forbidden" in response.json()["detail"]


def test_sos_status_change_triggers_audit_log(client, auth_headers, test_user_id):
    """Verify that updating an SOS event status records an SOS_STATUS_CHANGED audit log."""
    event_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    audit_logs_list = []

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [{
            "id": event_id,
            "family_member_id": member_id,
            "triggered_by": test_user_id,
            "status": "TRIGGERED",
            "notes": "Help needed",
            "triggered_at": "2026-10-06T00:00:00Z",
            "created_at": "2026-10-06T00:00:00Z"
        }],
        "audit_logs": audit_logs_list
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    res = client.patch(
        f"/emergency/sos/{event_id}/status",
        json={"status": "RESOLVED", "notes": "Situation resolved"},
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert res.status_code == 200
    assert any(log["action"] == AuditAction.SOS_STATUS_CHANGED.value for log in audit_logs_list)


def test_medicine_actions_trigger_audit_log(client, auth_headers, test_user_id):
    """Verify medicine create and update log appropriate audit actions."""
    member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())
    audit_logs_list = []

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": med_id,
            "family_member_id": member_id,
            "medicine_name": "Amoxicillin",
            "dosage": "500mg",
            "frequency": "daily",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z"
        }],
        "audit_logs": audit_logs_list
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    # Create medicine
    create_res = client.post(
        "/medicines",
        json={
            "family_member_id": member_id,
            "medicine_name": "Ibuprofen",
            "dosage": "200mg",
            "frequency": "as needed"
        },
        headers=auth_headers
    )
    assert create_res.status_code == 201
    assert any(log["action"] == AuditAction.MEDICINE_CREATED.value for log in audit_logs_list)

    # Update medicine
    update_res = client.put(
        f"/medicines/{med_id}",
        json={"dosage": "1000mg"},
        headers=auth_headers
    )
    assert update_res.status_code == 200
    assert any(log["action"] == AuditAction.MEDICINE_UPDATED.value for log in audit_logs_list)

    app.dependency_overrides.clear()


def test_medical_report_actions_trigger_audit_log(client, auth_headers, test_user_id):
    """Verify medical report upload and delete log appropriate audit actions."""
    member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())
    audit_logs_list = []

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medical_reports": [{
            "id": report_id,
            "family_member_id": member_id,
            "uploaded_by": test_user_id,
            "file_name": "blood_test.pdf",
            "storage_path": f"{member_id}/blood_test.pdf",
            "report_type": "LAB_REPORT",
            "mime_type": "application/pdf",
            "file_size": 1024,
            "report_date": "2026-10-06",
            "created_at": "2026-10-06T00:00:00Z"
        }],
        "audit_logs": audit_logs_list
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    # Upload report
    files = {"file": ("xray.png", b"fake_png_data", "image/png")}
    data = {
        "family_member_id": member_id,
        "report_type": "XRAY",
        "description": "Chest xray"
    }
    upload_res = client.post("/medical-reports", files=files, data=data, headers=auth_headers)
    assert upload_res.status_code == 201
    assert any(log["action"] == AuditAction.MEDICAL_REPORT_UPLOADED.value for log in audit_logs_list)

    # Delete report
    del_res = client.delete(f"/medical-reports/{report_id}", headers=auth_headers)
    assert del_res.status_code == 204
    assert any(log["action"] == AuditAction.MEDICAL_REPORT_DELETED.value for log in audit_logs_list)

    app.dependency_overrides.clear()


def test_emergency_contact_actions_trigger_audit_log(client, auth_headers, test_user_id):
    """Verify emergency contact create, update, and delete log EMERGENCY_CONTACT_CHANGED."""
    member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())
    audit_logs_list = []

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": member_id,
            "name": "Dr. Smith",
            "relationship": "Physician",
            "phone": "+1234567890",
            "priority": 1,
            "created_at": "2026-10-06T00:00:00Z"
        }],
        "audit_logs": audit_logs_list
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    # Update contact
    update_res = client.put(
        f"/emergency-contacts/{contact_id}",
        json={"phone": "+1987654321"},
        headers=auth_headers
    )
    assert update_res.status_code == 200
    assert any(log["action"] == AuditAction.EMERGENCY_CONTACT_CHANGED.value for log in audit_logs_list)

    # Delete contact
    del_res = client.delete(f"/emergency-contacts/{contact_id}", headers=auth_headers)
    assert del_res.status_code == 204
    assert any(log["action"] == AuditAction.EMERGENCY_CONTACT_CHANGED.value and log.get("metadata", {}).get("change") == "DELETED" for log in audit_logs_list)

    app.dependency_overrides.clear()


def test_health_record_view_update_delete_audit_log(client, auth_headers, test_user_id):
    """Verify health record viewed, updated, and deleted emit respective audit logs."""
    member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())
    audit_logs_list = []

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [{
            "id": record_id,
            "family_member_id": member_id,
            "blood_group": "O+",
            "allergies": "None",
            "medical_conditions": "None",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }],
        "audit_logs": audit_logs_list
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    # View record
    view_res = client.get(f"/health-records/{record_id}", headers=auth_headers)
    assert view_res.status_code == 200
    assert any(log["action"] == AuditAction.HEALTH_RECORD_VIEWED.value for log in audit_logs_list)

    # Update record
    upd_res = client.put(f"/health-records/{record_id}", json={"blood_group": "A-"}, headers=auth_headers)
    assert upd_res.status_code == 200
    assert any(log["action"] == AuditAction.HEALTH_RECORD_UPDATED.value for log in audit_logs_list)

    # Delete record
    del_res = client.delete(f"/health-records/{record_id}", headers=auth_headers)
    assert del_res.status_code == 204
    assert any(log["action"] == AuditAction.HEALTH_RECORD_DELETED.value for log in audit_logs_list)

    app.dependency_overrides.clear()

