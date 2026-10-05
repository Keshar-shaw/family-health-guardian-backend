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

    def order(self, column, desc=False):
        self._data.sort(key=lambda x: str(x.get(column, "")), reverse=desc)
        return self

    def range(self, start, end):
        self._data = self._data[start : end + 1]
        return self

    def gte(self, column, value):
        self._data = [item for item in self._data if str(item.get(column, "")) >= str(value)]
        return self

    def lte(self, column, value):
        self._data = [item for item in self._data if str(item.get(column, "")) <= str(value)]
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


def test_get_sos_history_self_and_family(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    event_1 = str(uuid.uuid4())
    event_2 = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [
            {
                "id": event_1,
                "family_member_id": family_member_id,
                "triggered_by": test_user_id,
                "status": "RESOLVED",
                "triggered_at": "2026-10-05T10:00:00Z"
            },
            {
                "id": event_2,
                "family_member_id": family_member_id,
                "triggered_by": test_user_id,
                "status": "TRIGGERED",
                "triggered_at": "2026-10-06T12:00:00Z"
            }
        ]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/emergency/sos/history", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Verify ordered newest first
    assert data[0]["id"] == event_2
    assert data[1]["id"] == event_1


def test_get_sos_history_filtered_by_member(client, auth_headers, test_user_id):
    member_1 = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    event_1 = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": member_1,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [
            {
                "id": event_1,
                "family_member_id": member_1,
                "triggered_by": test_user_id,
                "status": "TRIGGERED",
                "triggered_at": "2026-10-06T12:00:00Z"
            }
        ]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency/sos/history?family_member_id={member_1}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == event_1


def test_get_sos_history_filtered_by_status(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    event_triggered = str(uuid.uuid4())
    event_resolved = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [
            {
                "id": event_triggered,
                "family_member_id": family_member_id,
                "triggered_by": test_user_id,
                "status": "TRIGGERED",
                "triggered_at": "2026-10-06T12:00:00Z"
            },
            {
                "id": event_resolved,
                "family_member_id": family_member_id,
                "triggered_by": test_user_id,
                "status": "RESOLVED",
                "triggered_at": "2026-10-05T10:00:00Z"
            }
        ]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/emergency/sos/history?status=TRIGGERED", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == event_triggered
    assert data[0]["status"] == "TRIGGERED"


def test_get_sos_history_filtered_by_date(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    event_oct_1 = str(uuid.uuid4())
    event_oct_5 = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": [
            {
                "id": event_oct_1,
                "family_member_id": family_member_id,
                "triggered_by": test_user_id,
                "status": "RESOLVED",
                "triggered_at": "2026-10-01T10:00:00Z"
            },
            {
                "id": event_oct_5,
                "family_member_id": family_member_id,
                "triggered_by": test_user_id,
                "status": "RESOLVED",
                "triggered_at": "2026-10-05T10:00:00Z"
            }
        ]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/emergency/sos/history?start_date=2026-10-04&end_date=2026-10-06", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == event_oct_5


def test_get_sos_history_pagination(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    events = [
        {
            "id": str(uuid.uuid4()),
            "family_member_id": family_member_id,
            "triggered_by": test_user_id,
            "status": "TRIGGERED",
            "triggered_at": f"2026-10-0{i+1}T10:00:00Z"
        }
        for i in range(5)
    ]

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "sos_events": events
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    # Request limit=2, offset=0 (first 2 of newest)
    res_page_1 = client.get("/emergency/sos/history?limit=2&offset=0", headers=auth_headers)
    # Request limit=2, offset=2 (next 2)
    res_page_2 = client.get("/emergency/sos/history?limit=2&offset=2", headers=auth_headers)
    app.dependency_overrides.clear()

    assert res_page_1.status_code == 200
    assert len(res_page_1.json()) == 2
    assert res_page_2.status_code == 200
    assert len(res_page_2.json()) == 2
    assert res_page_1.json()[0]["id"] != res_page_2.json()[0]["id"]


def test_get_sos_history_unauthorized_member_forbidden(client, auth_headers, test_user_id):
    other_patient_id = str(uuid.uuid4())
    unrelated_member_id = str(uuid.uuid4())
    other_family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [
            {
                "id": unrelated_member_id,
                "family_id": other_family_id,
                "user_id": other_patient_id,
                "role": "MEMBER"
            }
        ],
        "sos_events": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency/sos/history?family_member_id={unrelated_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_trigger_sos_with_full_location_fields(client, auth_headers, test_user_id):
    """Test triggering SOS with explicitly supplied valid location: lat, lon, accuracy, timestamp."""
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
        "notifications": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "latitude": 37.7749,
        "longitude": -122.4194,
        "accuracy": 12.5,
        "timestamp": "2026-10-06T02:00:00Z",
        "notes": "Fall detection with GPS fix"
    }

    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["latitude"] == 37.7749
    assert data["longitude"] == -122.4194
    assert data["accuracy"] == 12.5
    assert data["location_accuracy"] == 12.5
    assert data["timestamp"] is not None
    assert data["notes"] == "Fall detection with GPS fix"


def test_trigger_sos_without_location_succeeds(client, auth_headers, test_user_id):
    """Verify that location is completely optional and omitting it succeeds without error."""
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
        "notifications": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "notes": "Panic button pressed without GPS"
    }

    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["latitude"] is None
    assert data["longitude"] is None
    assert data["accuracy"] is None
    assert data["notes"] == "Panic button pressed without GPS"


def test_trigger_sos_partial_coordinates_rejected(client, auth_headers, test_user_id):
    """Reject SOS request when only one coordinate is provided (latitude without longitude or vice versa)."""
    family_member_id = str(uuid.uuid4())

    # Only latitude provided
    payload_only_lat = {
        "family_member_id": family_member_id,
        "latitude": 40.7128
    }
    response_lat = client.post("/emergency/sos", json=payload_only_lat, headers=auth_headers)
    assert response_lat.status_code == 422

    # Only longitude provided
    payload_only_lon = {
        "family_member_id": family_member_id,
        "longitude": -74.0060
    }
    response_lon = client.post("/emergency/sos", json=payload_only_lon, headers=auth_headers)
    assert response_lon.status_code == 422


def test_trigger_sos_negative_accuracy_rejected(client, auth_headers, test_user_id):
    """Reject negative location accuracy."""
    family_member_id = str(uuid.uuid4())

    payload = {
        "family_member_id": family_member_id,
        "latitude": 40.7128,
        "longitude": -74.0060,
        "accuracy": -10.0
    }
    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    assert response.status_code == 422


def test_trigger_sos_coordinate_bounds_rejected(client, auth_headers, test_user_id):
    """Reject coordinates exceeding valid geographical bounds."""
    family_member_id = str(uuid.uuid4())

    # Latitude > 90
    res1 = client.post(
        "/emergency/sos",
        json={"family_member_id": family_member_id, "latitude": 90.1, "longitude": 0.0},
        headers=auth_headers
    )
    assert res1.status_code == 422

    # Latitude < -90
    res2 = client.post(
        "/emergency/sos",
        json={"family_member_id": family_member_id, "latitude": -90.1, "longitude": 0.0},
        headers=auth_headers
    )
    assert res2.status_code == 422

    # Longitude > 180
    res3 = client.post(
        "/emergency/sos",
        json={"family_member_id": family_member_id, "latitude": 0.0, "longitude": 180.1},
        headers=auth_headers
    )
    assert res3.status_code == 422

    # Longitude < -180
    res4 = client.post(
        "/emergency/sos",
        json={"family_member_id": family_member_id, "latitude": 0.0, "longitude": -180.1},
        headers=auth_headers
    )
    assert res4.status_code == 422


def test_location_data_protected_by_sos_authorization(client, auth_headers, test_user_id):
    """Ensure location coordinates in an SOS event are shielded from unauthorized users."""
    event_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    other_family_id = str(uuid.uuid4())
    other_member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": other_member_id,
            "family_id": other_family_id,
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "sos_events": [{
            "id": event_id,
            "family_member_id": other_member_id,
            "triggered_by": other_patient_id,
            "status": "TRIGGERED",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "accuracy": 5.0,
            "triggered_at": "2026-10-06T02:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    # Caller does not belong to other_family_id
    response = client.get(f"/emergency/sos/{event_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "Access forbidden" in response.json()["detail"]
