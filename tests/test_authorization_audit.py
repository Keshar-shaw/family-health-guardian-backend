import pytest
import uuid
from unittest.mock import MagicMock
from app.auth.dependencies import get_supabase
from app.main import app


class MockQueryBuilder:
    def __init__(self, data=None):
        self._data = [dict(item) for item in data] if data is not None else []
    
    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self._data = [item for item in self._data if str(item.get(column)) == str(value)]
        return self

    def in_(self, column, values):
        val_strs = [str(v) for v in values]
        self._data = [item for item in self._data if str(item.get(column)) in val_strs]
        return self

    def or_(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def lte(self, *args, **kwargs):
        return self

    def insert(self, payload):
        p = dict(payload)
        if "id" not in p:
            p["id"] = str(uuid.uuid4())
        p.setdefault("created_at", "2026-10-06T00:00:00Z")
        p.setdefault("updated_at", "2026-10-06T00:00:00Z")
        self._data = [p]
        return self

    def update(self, payload):
        if self._data:
            updated = dict(self._data[0])
            updated.update(payload)
            updated["updated_at"] = "2026-10-06T01:00:00Z"
            self._data = [updated]
        return self

    def delete(self):
        return self

    def execute(self):
        res = MagicMock()
        res.data = list(self._data)
        return res


def setup_mock_supabase(tables_data):
    mock_supabase = MagicMock()

    def get_table(name):
        data = tables_data.get(name, [])
        return MockQueryBuilder(data)

    mock_supabase.table.side_effect = get_table
    return mock_supabase


# -------------------------------------------------------------
# 1. Unrelated Family Isolation Tests
# -------------------------------------------------------------

def test_unrelated_family_cannot_view_family_details(client, auth_headers, test_user_id):
    """User in Family A cannot view details of Family B."""
    family_b_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "families": [{
            "id": family_b_id,
            "name": "Family B",
            "created_by": other_user_id
        }],
        "family_members": [{
            "id": str(uuid.uuid4()),
            "family_id": family_b_id,
            "user_id": other_user_id,
            "role": "ADMIN"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/families/{family_b_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


def test_unrelated_family_cannot_access_health_records(client, auth_headers, test_user_id):
    """User cannot access health records of a member in an unrelated family."""
    unrelated_member_id = str(uuid.uuid4())
    unrelated_family_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": unrelated_member_id,
            "family_id": unrelated_family_id,
            "user_id": other_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "health_records": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/health-records?family_member_id={unrelated_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unrelated_family_cannot_access_medicines(client, auth_headers, test_user_id):
    """User cannot access medicines of a member in an unrelated family."""
    unrelated_member_id = str(uuid.uuid4())
    unrelated_family_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": unrelated_member_id,
            "family_id": unrelated_family_id,
            "user_id": other_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicines": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/medicines?family_member_id={unrelated_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unrelated_family_cannot_trigger_sos(client, auth_headers, test_user_id):
    """User cannot trigger SOS for a member of an unrelated family."""
    unrelated_member_id = str(uuid.uuid4())
    unrelated_family_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": unrelated_member_id,
            "family_id": unrelated_family_id,
            "user_id": other_user_id,
            "role": "MEMBER"
        }],
        "sos_events": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "family_member_id": unrelated_member_id,
        "latitude": 40.7128,
        "longitude": -74.0060
    }
    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unrelated_family_cannot_access_emergency_contacts(client, auth_headers, test_user_id):
    """User cannot access emergency contacts of an unrelated family member."""
    unrelated_member_id = str(uuid.uuid4())
    unrelated_family_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": unrelated_member_id,
            "family_id": unrelated_family_id,
            "user_id": other_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "emergency_contacts": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/emergency-contacts?family_member_id={unrelated_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unrelated_family_cannot_access_medical_reports(client, auth_headers, test_user_id):
    """User cannot view medical reports of an unrelated family member."""
    unrelated_member_id = str(uuid.uuid4())
    unrelated_family_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": unrelated_member_id,
            "family_id": unrelated_family_id,
            "user_id": other_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medical_reports": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/medical-reports?family_member_id={unrelated_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


# -------------------------------------------------------------
# 2. Consent Authorization & Privilege Escalation Tests
# -------------------------------------------------------------

def test_grantee_cannot_approve_own_consent(client, auth_headers, test_user_id):
    """Grantee cannot activate / approve a pending consent request (only granter can)."""
    consent_id = str(uuid.uuid4())
    granter_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "consents": [{
            "id": consent_id,
            "granter_id": granter_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "status": "PENDING"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    # Grantee attempts to self-approve
    response = client.patch(
        f"/consents/{consent_id}",
        json={"status": "ACTIVE"},
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Only the patient (granter) can approve" in response.json()["detail"]


def test_grantee_cannot_elevate_permission_level(client, auth_headers, test_user_id):
    """Grantee cannot elevate their permission level to FULL_ACCESS."""
    consent_id = str(uuid.uuid4())
    granter_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "consents": [{
            "id": consent_id,
            "granter_id": granter_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "status": "ACTIVE"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.patch(
        f"/consents/{consent_id}",
        json={"permission_level": "FULL_ACCESS"},
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Only the patient (granter) can change consent permission" in response.json()["detail"]


def test_cannot_create_consent_for_unrelated_family_users(client, auth_headers, test_user_id):
    """User cannot request or grant consent with a user not in the same family."""
    family_id = str(uuid.uuid4())
    unrelated_grantee_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": str(uuid.uuid4()),
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.post(
        "/consents",
        json={
            "grantee_id": unrelated_grantee_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY"
        },
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Grantee is not a member" in response.json()["detail"]


def test_cannot_create_consent_to_oneself(client, auth_headers, test_user_id):
    """User cannot grant consent to themselves."""
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": str(uuid.uuid4()),
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.post(
        "/consents",
        json={
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY"
        },
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "oneself" in response.json()["detail"]


# -------------------------------------------------------------
# 3. Client Untrusted ID & Cross-Resource Tampering Tests
# -------------------------------------------------------------

def test_reject_mismatched_family_member_id_in_medicine_log(client, auth_headers, test_user_id):
    """Never trust client-supplied family_member_id if it mismatches the medicine's actual owner."""
    medicine_id = str(uuid.uuid4())
    actual_member_id = str(uuid.uuid4())
    spoofed_member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "medicines": [{
            "id": medicine_id,
            "family_member_id": actual_member_id,
            "medicine_name": "Lisinopril"
        }],
        "family_members": [{
            "id": actual_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicine_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "medicine_id": medicine_id,
        "family_member_id": spoofed_member_id,
        "status": "TAKEN"
    }
    response = client.post("/medicine-logs", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "does not match the medicine's family member" in response.json()["detail"]


def test_reject_mismatched_schedule_id_in_medicine_log(client, auth_headers, test_user_id):
    """Reject schedule_id that belongs to a different medicine."""
    medicine_a_id = str(uuid.uuid4())
    medicine_b_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())
    schedule_b_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "medicines": [
            {"id": medicine_a_id, "family_member_id": member_id, "medicine_name": "Med A"},
            {"id": medicine_b_id, "family_member_id": member_id, "medicine_name": "Med B"}
        ],
        "medicine_schedules": [
            {"id": schedule_b_id, "medicine_id": medicine_b_id, "scheduled_time": "08:00"}
        ],
        "family_members": [{
            "id": member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicine_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "medicine_id": medicine_a_id,
        "schedule_id": schedule_b_id,
        "status": "TAKEN"
    }
    response = client.post("/medicine-logs", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Schedule does not belong to the specified medicine" in response.json()["detail"]


# -------------------------------------------------------------
# 4. RBAC Authorization Tests
# -------------------------------------------------------------

def test_non_admin_cannot_add_family_member(client, auth_headers, test_user_id):
    """Only family ADMINs can add members to a family."""
    family_id = str(uuid.uuid4())
    new_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": str(uuid.uuid4()),
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"  # Non-admin
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.post(
        f"/families/{family_id}/members",
        json={"user_id": new_user_id, "role": "MEMBER"},
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Only family ADMINs" in response.json()["detail"]


def test_non_admin_cannot_remove_other_family_member(client, auth_headers, test_user_id):
    """Non-admin cannot remove other members from a family."""
    family_id = str(uuid.uuid4())
    other_member_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": str(uuid.uuid4()),
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"  # Non-admin
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.delete(
        f"/families/{family_id}/members/{other_member_user_id}",
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Only family ADMINs or self" in response.json()["detail"]


# -------------------------------------------------------------
# 5. Read-Only vs Full-Access Modification Prevention Tests
# -------------------------------------------------------------

def test_read_only_consent_cannot_delete_medical_report(client, auth_headers, test_user_id):
    """User with READ_ONLY consent cannot delete a medical report."""
    report_id = str(uuid.uuid4())
    patient_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": patient_member_id,
            "family_id": family_id,
            "user_id": patient_user_id,
            "role": "MEMBER"
        }],
        "consents": [{
            "id": str(uuid.uuid4()),
            "granter_id": patient_user_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "status": "ACTIVE"
        }],
        "medical_reports": [{
            "id": report_id,
            "family_member_id": patient_member_id,
            "storage_path": f"{patient_member_id}/report.pdf",
            "file_name": "report.pdf"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.delete(f"/medical-reports/{report_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "FULL_ACCESS" in response.json()["detail"]


def test_read_only_consent_cannot_update_emergency_contact(client, auth_headers, test_user_id):
    """User with READ_ONLY consent cannot modify an emergency contact."""
    contact_id = str(uuid.uuid4())
    patient_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": patient_member_id,
            "family_id": family_id,
            "user_id": patient_user_id,
            "role": "MEMBER"
        }],
        "consents": [{
            "id": str(uuid.uuid4()),
            "granter_id": patient_user_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "status": "ACTIVE"
        }],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": patient_member_id,
            "name": "Old Name",
            "phone": "+1234567890",
            "priority": 1,
            "is_active": True
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.put(
        f"/emergency-contacts/{contact_id}",
        json={"name": "New Name"},
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "FULL_ACCESS" in response.json()["detail"]


def test_unrelated_family_cannot_access_medicine_schedules(client, auth_headers, test_user_id):
    """User cannot access medicine schedules of an unrelated family member."""
    unrelated_member_id = str(uuid.uuid4())
    unrelated_med_id = str(uuid.uuid4())
    unrelated_family_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": unrelated_member_id,
            "family_id": unrelated_family_id,
            "user_id": other_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": unrelated_med_id,
            "family_member_id": unrelated_member_id,
            "medicine_name": "Atorvastatin"
        }],
        "medicine_schedules": [{
            "id": str(uuid.uuid4()),
            "medicine_id": unrelated_med_id,
            "scheduled_time": "09:00"
        }],
        "consents": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/medicine-schedules?family_member_id={unrelated_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unrelated_family_cannot_access_medicine_logs(client, auth_headers, test_user_id):
    """User cannot access medicine logs of an unrelated family member."""
    unrelated_member_id = str(uuid.uuid4())
    unrelated_med_id = str(uuid.uuid4())
    unrelated_family_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": unrelated_member_id,
            "family_id": unrelated_family_id,
            "user_id": other_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": unrelated_med_id,
            "family_member_id": unrelated_member_id,
            "medicine_name": "Metformin"
        }],
        "medicine_logs": [{
            "id": str(uuid.uuid4()),
            "medicine_id": unrelated_med_id,
            "family_member_id": unrelated_member_id,
            "status": "TAKEN"
        }],
        "consents": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get(f"/medicine-logs?family_member_id={unrelated_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_read_only_consent_cannot_create_health_record(client, auth_headers, test_user_id):
    """User with READ_ONLY consent cannot create a new health record for the patient."""
    patient_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": patient_member_id,
            "family_id": family_id,
            "user_id": patient_user_id,
            "role": "MEMBER"
        }],
        "consents": [{
            "id": str(uuid.uuid4()),
            "granter_id": patient_user_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "status": "ACTIVE"
        }],
        "health_records": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "family_member_id": patient_member_id,
        "blood_group": "AB+"
    }
    response = client.post("/health-records", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "FULL_ACCESS" in response.json()["detail"]


def test_read_only_consent_cannot_create_medicine(client, auth_headers, test_user_id):
    """User with READ_ONLY consent cannot prescribe/add medicine for the patient."""
    patient_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": patient_member_id,
            "family_id": family_id,
            "user_id": patient_user_id,
            "role": "MEMBER"
        }],
        "consents": [{
            "id": str(uuid.uuid4()),
            "granter_id": patient_user_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "status": "ACTIVE"
        }],
        "medicines": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "family_member_id": patient_member_id,
        "medicine_name": "Amoxicillin"
    }
    response = client.post("/medicines", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "FULL_ACCESS" in response.json()["detail"]


def test_caller_not_in_family_cannot_create_consent(client, auth_headers, test_user_id):
    """Caller who is not in the specified family cannot create a consent request."""
    family_id = str(uuid.uuid4())
    grantee_id = str(uuid.uuid4())

    # Caller is not listed in family_members of family_id
    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": str(uuid.uuid4()),
            "family_id": family_id,
            "user_id": grantee_id,
            "role": "MEMBER"
        }],
        "consents": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.post(
        "/consents",
        json={
            "grantee_id": grantee_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY"
        },
        headers=auth_headers
    )
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Caller is not a member" in response.json()["detail"]
