import pytest
import uuid
from unittest.mock import MagicMock
from app.auth.dependencies import get_supabase
from app.main import app
from app.schemas.notification import NotificationType, NotificationStatus
from app.services.notifications import (
    BaseNotificationProvider,
    InMemoryNotificationProvider,
    NotificationService,
    get_notification_provider,
    set_notification_provider,
)


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

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
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
            self._data = [updated]
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
# 1. Provider Abstraction Tests
# -------------------------------------------------------------

def test_custom_notification_provider_pluggability():
    """Verify that custom third-party providers can be seamlessly registered."""
    class CustomMockProvider(BaseNotificationProvider):
        def __init__(self):
            self.delivered = []

        def send(self, recipient_id, title, message, notification_type, metadata=None):
            self.delivered.append({
                "recipient_id": recipient_id,
                "title": title,
                "message": message,
                "type": notification_type
            })
            return True

    custom_provider = CustomMockProvider()
    original_provider = get_notification_provider()
    
    try:
        set_notification_provider(custom_provider)
        assert get_notification_provider() == custom_provider

        # Send test dispatch
        success = custom_provider.send(
            recipient_id="user-123",
            title="Test Alert",
            message="Test message body",
            notification_type="MEDICINE_REMINDER"
        )
        assert success is True
        assert len(custom_provider.delivered) == 1
        assert custom_provider.delivered[0]["title"] == "Test Alert"
    finally:
        set_notification_provider(original_provider)


# -------------------------------------------------------------
# 2. Service Layer Unit Tests
# -------------------------------------------------------------

def test_service_create_medicine_reminder_notification():
    """Test creating a medicine reminder notification via service."""
    patient_user_id = str(uuid.uuid4())
    family_member_id = uuid.uuid4()
    medicine_id = uuid.uuid4()

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": str(family_member_id),
            "user_id": patient_user_id,
            "family_id": str(uuid.uuid4()),
            "role": "MEMBER"
        }],
        "notifications": []
    })

    notif = NotificationService.create_medicine_reminder_notification(
        supabase=mock_db,
        medicine_id=medicine_id,
        family_member_id=family_member_id,
        scheduled_time="08:00 AM",
        medicine_name="Lisinopril",
        dosage="10mg"
    )

    assert notif["user_id"] == patient_user_id
    assert notif["type"] == NotificationType.MEDICINE_REMINDER.value
    assert "Lisinopril" in notif["title"]
    assert notif["status"] == NotificationStatus.SENT.value
    assert notif["sent_at"] is not None


def test_service_send_sos_notifications():
    """Test dispatching SOS notifications to patient and family members."""
    patient_user_id = str(uuid.uuid4())
    guardian_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    family_member_id = uuid.uuid4()

    mock_db = setup_mock_supabase({
        "family_members": [
            {"id": str(family_member_id), "user_id": patient_user_id, "family_id": family_id, "role": "MEMBER"},
            {"id": str(uuid.uuid4()), "user_id": guardian_user_id, "family_id": family_id, "role": "GUARDIAN"}
        ],
        "notifications": []
    })

    sos_event = {
        "id": str(uuid.uuid4()),
        "notes": "Chest pain reported",
        "latitude": 37.7749,
        "longitude": -122.4194
    }

    notifs = NotificationService.send_sos_notifications(
        supabase=mock_db,
        sos_event=sos_event,
        family_member_id=family_member_id,
        triggerer_user_id=patient_user_id
    )

    assert len(notifs) == 2
    types = {n["type"] for n in notifs}
    recipients = {n["user_id"] for n in notifs}
    assert types == {NotificationType.EMERGENCY_SOS.value}
    assert recipients == {patient_user_id, guardian_user_id}


# -------------------------------------------------------------
# 3. API Endpoint Tests
# -------------------------------------------------------------

def test_get_notifications_api(client, auth_headers, test_user_id):
    """Test retrieving user notifications via GET /notifications."""
    notif_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "notifications": [{
            "id": notif_id,
            "user_id": test_user_id,
            "family_member_id": member_id,
            "type": NotificationType.MEDICINE_REMINDER.value,
            "title": "Medicine Reminder",
            "message": "Take Aspirin",
            "status": NotificationStatus.SENT.value,
            "sent_at": "2026-10-06T08:00:00Z",
            "created_at": "2026-10-06T08:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.get("/notifications", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == notif_id
    assert data[0]["type"] == NotificationType.MEDICINE_REMINDER.value


def test_mark_notification_read_api(client, auth_headers, test_user_id):
    """Test marking notification as read via PATCH /notifications/{id}/read."""
    notif_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "notifications": [{
            "id": notif_id,
            "user_id": test_user_id,
            "family_member_id": member_id,
            "type": NotificationType.EMERGENCY_SOS.value,
            "title": "SOS Alert",
            "message": "Emergency alert",
            "status": NotificationStatus.SENT.value,
            "sent_at": "2026-10-06T08:00:00Z",
            "created_at": "2026-10-06T08:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.patch(f"/notifications/{notif_id}/read", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == NotificationStatus.READ.value


def test_mark_other_user_notification_read_forbidden(client, auth_headers, test_user_id):
    """User cannot mark someone else's notification as read."""
    notif_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "notifications": [{
            "id": notif_id,
            "user_id": other_user_id,
            "family_member_id": member_id,
            "type": NotificationType.EMERGENCY_SOS.value,
            "title": "SOS Alert",
            "message": "Emergency alert",
            "status": NotificationStatus.SENT.value,
            "sent_at": "2026-10-06T08:00:00Z",
            "created_at": "2026-10-06T08:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    response = client.patch(f"/notifications/{notif_id}/read", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


# -------------------------------------------------------------
# 4. Trigger Integration Tests
# -------------------------------------------------------------

def test_sos_creates_emergency_notification(client, auth_headers, test_user_id):
    """Verify that triggering an SOS alert creates emergency notifications."""
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
        "notes": "Severe asthma attack"
    }
    response = client.post("/emergency/sos", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["notification_dispatched"] is True


def test_medicine_schedule_creates_reminder_notification(client, auth_headers, test_user_id):
    """Verify that creating a medicine schedule with reminder_enabled=True triggers reminder notification."""
    medicine_id = str(uuid.uuid4())
    family_member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": medicine_id,
            "family_member_id": family_member_id,
            "medicine_name": "Metoprolol",
            "dosage": "50mg"
        }],
        "medicine_schedules": [],
        "notifications": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db
    payload = {
        "medicine_id": medicine_id,
        "scheduled_time": "09:00 AM",
        "reminder_enabled": True
    }
    response = client.post("/medicine-schedules", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["reminder_enabled"] is True
