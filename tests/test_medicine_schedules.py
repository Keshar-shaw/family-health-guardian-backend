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
        p.setdefault("reminder_enabled", True)
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


def test_create_schedule_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id,
            "medicine_name": "Paracetamol"
        }],
        "medicine_schedules": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "medicine_id": medicine_id,
        "scheduled_time": "08:00 AM",
        "frequency_type": "DAILY",
        "days_of_week": ["MON", "TUE", "WED", "THU", "FRI"],
        "start_date": "2026-10-01",
        "end_date": "2026-10-15",
        "reminder_enabled": True
    }

    response = client.post("/medicine-schedules", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["medicine_id"] == medicine_id
    assert data["scheduled_time"] == "08:00 AM"
    assert data["frequency_type"] == "DAILY"
    assert data["reminder_enabled"] is True


def test_create_multiple_schedules_for_one_medicine(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id,
            "medicine_name": "Amoxicillin"
        }],
        "medicine_schedules": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    # Create morning dose
    res1 = client.post(
        "/medicine-schedules",
        json={"medicine_id": medicine_id, "scheduled_time": "08:00 AM"},
        headers=auth_headers
    )
    # Create afternoon dose
    res2 = client.post(
        "/medicine-schedules",
        json={"medicine_id": medicine_id, "scheduled_time": "02:00 PM"},
        headers=auth_headers
    )
    # Create evening dose
    res3 = client.post(
        "/medicine-schedules",
        json={"medicine_id": medicine_id, "scheduled_time": "08:00 PM"},
        headers=auth_headers
    )

    app.dependency_overrides.clear()

    assert res1.status_code == 201
    assert res2.status_code == 201
    assert res3.status_code == 201
    assert res1.json()["scheduled_time"] == "08:00 AM"
    assert res2.json()["scheduled_time"] == "02:00 PM"
    assert res3.json()["scheduled_time"] == "08:00 PM"


def test_create_schedule_guardian_with_full_access(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())

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
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id,
            "medicine_name": "Metformin"
        }],
        "medicine_schedules": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "medicine_id": medicine_id,
        "scheduled_time": "09:00 AM",
        "frequency_type": "DAILY"
    }

    response = client.post("/medicine-schedules", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["scheduled_time"] == "09:00 AM"


def test_create_schedule_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())

    # Read-only consent, cannot create schedule
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
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id,
            "medicine_name": "Metformin"
        }],
        "medicine_schedules": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "medicine_id": medicine_id,
        "scheduled_time": "09:00 AM"
    }

    response = client.post("/medicine-schedules", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_create_schedule_nonexistent_medicine(client, auth_headers):
    mock_db = setup_mock_supabase({"medicines": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "medicine_id": str(uuid.uuid4()),
        "scheduled_time": "12:00 PM"
    }

    response = client.post("/medicine-schedules", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Medicine not found"


def test_list_schedules_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "scheduled_time": "08:00 AM",
            "frequency_type": "DAILY",
            "reminder_enabled": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/medicine-schedules", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == schedule_id
    assert data[0]["scheduled_time"] == "08:00 AM"


def test_list_schedules_by_medicine_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "scheduled_time": "10:00 PM",
            "frequency_type": "DAILY",
            "reminder_enabled": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicine-schedules?medicine_id={medicine_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["scheduled_time"] == "10:00 PM"


def test_list_schedules_forbidden_medicine(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicine-schedules?medicine_id={medicine_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_get_schedule_by_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "scheduled_time": "08:00 PM",
            "frequency_type": "DAILY",
            "reminder_enabled": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicine-schedules/{schedule_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == schedule_id
    assert data["scheduled_time"] == "08:00 PM"


def test_get_schedule_not_found(client, auth_headers):
    mock_db = setup_mock_supabase({"medicine_schedules": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicine-schedules/{uuid.uuid4()}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Medicine schedule not found"


def test_update_schedule_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "scheduled_time": "08:00 AM",
            "frequency_type": "DAILY",
            "reminder_enabled": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"scheduled_time": "08:30 AM", "reminder_enabled": False}
    response = client.put(f"/medicine-schedules/{schedule_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["scheduled_time"] == "08:30 AM"
    assert data["reminder_enabled"] is False


def test_update_schedule_guardian_read_only_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

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
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "scheduled_time": "08:00 AM",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"scheduled_time": "09:00 AM"}
    response = client.put(f"/medicine-schedules/{schedule_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_update_schedule_empty_payload_bad_request(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "scheduled_time": "08:00 AM",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.put(f"/medicine-schedules/{schedule_id}", json={}, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "No fields provided for update"


def test_delete_schedule_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/medicine-schedules/{schedule_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 204


def test_delete_schedule_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/medicine-schedules/{schedule_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unauthenticated_request_rejected(client):
    response = client.get("/medicine-schedules")
    assert response.status_code in (401, 403)
