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
        self._data = [p]
        return self

    def update(self, payload):
        if self._data:
            updated = dict(self._data[0])
            updated.update(payload)
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


def test_create_medicine_log_taken_self(client, auth_headers, test_user_id):
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
        "medicine_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "medicine_id": medicine_id,
        "status": "TAKEN",
        "notes": "Dose ingested after dinner"
    }

    response = client.post("/medicine-logs", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["medicine_id"] == medicine_id
    assert data["family_member_id"] == family_member_id
    assert data["status"] == "TAKEN"
    assert data["taken_at"] is not None
    assert data["notes"] == "Dose ingested after dinner"


def test_create_medicine_log_missed_and_skipped(client, auth_headers, test_user_id):
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
            "medicine_name": "Antibiotic"
        }],
        "medicine_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    res_missed = client.post(
        "/medicine-logs",
        json={"medicine_id": medicine_id, "status": "MISSED", "notes": "Forgot to bring dose"},
        headers=auth_headers
    )
    res_skipped = client.post(
        "/medicine-logs",
        json={"medicine_id": medicine_id, "status": "SKIPPED", "notes": "Fasting before test"},
        headers=auth_headers
    )

    app.dependency_overrides.clear()

    assert res_missed.status_code == 201
    assert res_missed.json()["status"] == "MISSED"
    assert res_skipped.status_code == 201
    assert res_skipped.json()["status"] == "SKIPPED"


def test_create_medicine_log_with_schedule_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    schedule_id = str(uuid.uuid4())
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
            "family_member_id": family_member_id
        }],
        "medicine_schedules": [{
            "id": schedule_id,
            "medicine_id": medicine_id
        }],
        "medicine_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "medicine_id": medicine_id,
        "schedule_id": schedule_id,
        "scheduled_at": "2026-10-06T08:00:00Z",
        "status": "TAKEN"
    }

    response = client.post("/medicine-logs", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["schedule_id"] == schedule_id
    assert data["status"] == "TAKEN"


def test_create_medicine_log_guardian_with_full_access(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": patient_user_id,
            "role": "MEMBER"
        }],
        "consents": [{
            "id": str(uuid.uuid4()),
            "granter_id": patient_user_id,
            "grantee_id": test_user_id,
            "family_id": family_id,
            "permission_level": "FULL_ACCESS",
            "status": "ACTIVE"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "medicine_id": medicine_id,
        "status": "TAKEN",
        "notes": "Administered by guardian"
    }

    response = client.post("/medicine-logs", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["notes"] == "Administered by guardian"


def test_create_medicine_log_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    # Read-only consent should not allow creating log
    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
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
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id
        }],
        "medicine_logs": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"medicine_id": medicine_id, "status": "TAKEN"}
    response = client.post("/medicine-logs", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_create_medicine_log_nonexistent_medicine(client, auth_headers):
    mock_db = setup_mock_supabase({"medicines": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"medicine_id": str(uuid.uuid4()), "status": "TAKEN"}
    response = client.post("/medicine-logs", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Medicine not found"


def test_list_medicine_logs_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicine_logs": [{
            "id": log_id,
            "medicine_id": medicine_id,
            "family_member_id": family_member_id,
            "status": "TAKEN",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/medicine-logs", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == log_id
    assert data[0]["status"] == "TAKEN"


def test_list_medicine_logs_filtered_by_medicine(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())

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
        "medicine_logs": [{
            "id": log_id,
            "medicine_id": medicine_id,
            "family_member_id": family_member_id,
            "status": "MISSED",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicine-logs?medicine_id={medicine_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "MISSED"


def test_list_medicine_logs_filtered_by_status(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicine_logs": [
            {
                "id": str(uuid.uuid4()),
                "medicine_id": medicine_id,
                "family_member_id": family_member_id,
                "status": "TAKEN",
                "created_at": "2026-10-06T00:00:00Z"
            },
            {
                "id": str(uuid.uuid4()),
                "medicine_id": medicine_id,
                "family_member_id": family_member_id,
                "status": "MISSED",
                "created_at": "2026-10-06T00:00:00Z"
            }
        ]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/medicine-logs?log_status=MISSED", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "MISSED"


def test_get_medicine_log_by_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicine_logs": [{
            "id": log_id,
            "medicine_id": medicine_id,
            "family_member_id": family_member_id,
            "status": "TAKEN",
            "notes": "Felt good",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicine-logs/{log_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == log_id
    assert data["notes"] == "Felt good"


def test_get_medicine_log_not_found(client, auth_headers):
    mock_db = setup_mock_supabase({"medicine_logs": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicine-logs/{uuid.uuid4()}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Medicine log not found"


def test_patch_status_to_taken(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicine_logs": [{
            "id": log_id,
            "medicine_id": medicine_id,
            "family_member_id": family_member_id,
            "status": "MISSED",
            "taken_at": None,
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"status": "TAKEN", "notes": "Taken late with water"}
    response = client.patch(f"/medicine-logs/{log_id}/status", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "TAKEN"
    assert data["notes"] == "Taken late with water"
    assert data["taken_at"] is not None


def test_patch_status_to_missed(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicine_logs": [{
            "id": log_id,
            "medicine_id": medicine_id,
            "family_member_id": family_member_id,
            "status": "TAKEN",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"status": "MISSED", "notes": "Corrected: patient was asleep"}
    response = client.patch(f"/medicine-logs/{log_id}/status", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "MISSED"
    assert data["notes"] == "Corrected: patient was asleep"


def test_patch_status_guardian_read_only_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    medicine_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
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
        "medicine_logs": [{
            "id": log_id,
            "medicine_id": medicine_id,
            "family_member_id": family_member_id,
            "status": "MISSED",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"status": "TAKEN"}
    response = client.patch(f"/medicine-logs/{log_id}/status", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unauthenticated_request_rejected(client):
    response = client.get("/medicine-logs")
    assert response.status_code in (401, 403)
