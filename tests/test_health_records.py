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


def test_create_health_record_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "blood_group": "O+",
        "allergies": "Penicillin",
        "chronic_conditions": "Asthma",
        "doctor_name": "Dr. Sarah",
        "doctor_contact": "+1987654321",
        "notes": "Regular inhaler use"
    }

    response = client.post("/health-records", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["family_member_id"] == family_member_id
    assert data["blood_group"] == "O+"
    assert data["allergies"] == "Penicillin"
    assert data["chronic_conditions"] == "Asthma"


def test_create_health_record_guardian_with_full_access(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [{
            "id": str(uuid.uuid4()),
            "granter_id": other_patient_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "FULL_ACCESS",
            "status": "ACTIVE"
        }],
        "health_records": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "blood_group": "A+",
        "notes": "Guardian updated records"
    }

    response = client.post("/health-records", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["blood_group"] == "A+"


def test_create_health_record_unauthorized_member_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    # No active consent granted
    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "blood_group": "B+"
    }

    response = client.post("/health-records", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_create_health_record_nonexistent_member(client, auth_headers):
    # Member not found in database
    mock_db = setup_mock_supabase({"family_members": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": str(uuid.uuid4()),
        "blood_group": "AB+"
    }

    response = client.post("/health-records", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Family member not found"


def test_list_health_records(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "blood_group": "O-",
            "allergies": "Dust",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/health-records", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == record_id
    assert data[0]["blood_group"] == "O-"


def test_get_health_record_by_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "blood_group": "B-",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/health-records/{record_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == record_id
    assert data["blood_group"] == "B-"


def test_get_health_record_not_found(client, auth_headers):
    mock_db = setup_mock_supabase({"health_records": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/health-records/{uuid.uuid4()}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Health record not found"


def test_update_health_record_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "blood_group": "O+",
            "allergies": "None",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"allergies": "Seasonal pollen", "doctor_name": "Dr. Watson"}
    response = client.put(f"/health-records/{record_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["allergies"] == "Seasonal pollen"
    assert data["doctor_name"] == "Dr. Watson"


def test_update_health_record_guardian_read_only_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    # Only READ_ONLY consent, not FULL_ACCESS
    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [{
            "id": str(uuid.uuid4()),
            "granter_id": other_patient_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "status": "ACTIVE"
        }],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "blood_group": "A+",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"notes": "Unauthorized edit attempt"}
    response = client.put(f"/health-records/{record_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_delete_health_record_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/health-records/{record_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 204


def test_delete_health_record_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    # Not self, no consent
    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/health-records/{record_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unauthenticated_request_rejected(client):
    response = client.get("/health-records")
    assert response.status_code in (401, 403)


def test_list_health_records_filtered_by_member_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "blood_group": "AB+",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/health-records?family_member_id={family_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == record_id


def test_list_health_records_filtered_by_member_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "health_records": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/health-records?family_member_id={family_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_get_health_record_other_member_without_consent_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "blood_group": "A-",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/health-records/{record_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_update_health_record_empty_payload_bad_request(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [{
            "id": record_id,
            "family_member_id": family_member_id,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.put(f"/health-records/{record_id}", json={}, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "No fields provided for update"
