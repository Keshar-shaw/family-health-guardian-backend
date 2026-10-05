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
        p.setdefault("status", "TRIGGERED")
        p.setdefault("triggered_at", "2026-10-06T00:00:00Z")
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


def test_trigger_sos_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [
            {"id": str(uuid.uuid4()), "family_member_id": family_member_id, "is_active": True},
            {"id": str(uuid.uuid4()), "family_member_id": family_member_id, "is_active": True}
        ],
        "sos_events": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "latitude": 37.7749,
        "longitude": -122.4194,
        "location_accuracy": 5.0,
        "notes": "Severe chest tightness"
    }

    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["family_member_id"] == family_member_id
    assert data["triggered_by"] == test_user_id
    assert data["status"] == "TRIGGERED"
    assert data["latitude"] == 37.7749
    assert data["longitude"] == -122.4194
    assert data["location_accuracy"] == 5.0
    assert data["notes"] == "Severe chest tightness"
    assert data["notification_dispatched"] is True
    assert data["emergency_contacts_count"] == 2


def test_trigger_sos_family_member(client, auth_headers, test_user_id):
    patient_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    # Caller is in the same family as the patient
    mock_db = setup_mock_supabase({
        "family_members": [
            {
                "id": patient_member_id,
                "family_id": family_id,
                "user_id": patient_user_id,
                "role": "MEMBER"
            },
            {
                "id": str(uuid.uuid4()),
                "family_id": family_id,
                "user_id": test_user_id,
                "role": "GUARDIAN"
            }
        ],
        "emergency_contacts": [],
        "sos_events": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": patient_member_id,
        "notes": "Elderly parent fell in living room"
    }

    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["family_member_id"] == patient_member_id
    assert data["triggered_by"] == test_user_id
    assert data["status"] == "TRIGGERED"


def test_trigger_sos_unrelated_user_forbidden(client, auth_headers, test_user_id):
    patient_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    # Caller is NOT in the patient's family
    mock_db = setup_mock_supabase({
        "family_members": [
            {
                "id": patient_member_id,
                "family_id": family_id,
                "user_id": patient_user_id,
                "role": "MEMBER"
            }
        ],
        "sos_events": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"family_member_id": patient_member_id}
    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "caller is not in the same family" in response.json()["detail"]


def test_trigger_sos_nonexistent_member(client, auth_headers):
    mock_db = setup_mock_supabase({"family_members": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"family_member_id": str(uuid.uuid4())}
    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Family member not found"


def test_trigger_sos_invalid_coordinates(client, auth_headers):
    payload = {
        "family_member_id": str(uuid.uuid4()),
        "latitude": 150.0  # Latitude must be between -90 and 90
    }
    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    assert response.status_code == 422


def test_get_sos_event_by_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [{
            "id": event_id,
            "family_member_id": family_member_id,
            "triggered_by": test_user_id,
            "status": "TRIGGERED",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "notes": "Emergency alert",
            "triggered_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency/sos/{event_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == event_id
    assert data["status"] == "TRIGGERED"
    assert data["latitude"] == 40.7128


def test_get_sos_event_not_found(client, auth_headers):
    mock_db = setup_mock_supabase({"sos_events": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency/sos/{uuid.uuid4()}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "SOS event not found"


def test_get_sos_event_unrelated_user_forbidden(client, auth_headers, test_user_id):
    patient_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    # Caller is unrelated
    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": patient_member_id,
            "family_id": family_id,
            "user_id": patient_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [{
            "id": event_id,
            "family_member_id": patient_member_id,
            "triggered_by": patient_user_id,
            "status": "TRIGGERED",
            "triggered_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency/sos/{event_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_patch_sos_status_acknowledge(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [{
            "id": event_id,
            "family_member_id": family_member_id,
            "triggered_by": test_user_id,
            "status": "TRIGGERED",
            "triggered_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"status": "ACKNOWLEDGED", "notes": "Guardian is en route"}
    response = client.patch(f"/emergency/sos/{event_id}/status", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ACKNOWLEDGED"
    assert data["notes"] == "Guardian is en route"


def test_patch_sos_status_resolve_and_cancel(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [{
            "id": event_id,
            "family_member_id": family_member_id,
            "triggered_by": test_user_id,
            "status": "ACKNOWLEDGED",
            "triggered_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"status": "RESOLVED", "notes": "Paramedics arrived, patient stabilized"}
    response = client.patch(f"/emergency/sos/{event_id}/status", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RESOLVED"
    assert data["resolved_at"] is not None


def test_unauthenticated_request_rejected(client):
    response = client.post("/emergency/sos", json={"family_member_id": str(uuid.uuid4())})
    assert response.status_code in (401, 403)
