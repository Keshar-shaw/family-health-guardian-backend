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

    def order(self, column, **kwargs):
        return self

    def insert(self, payload):
        p = dict(payload)
        if "id" not in p:
            p["id"] = str(uuid.uuid4())
        p.setdefault("is_active", True)
        p.setdefault("priority", 1)
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


def test_create_emergency_contact_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "name": "Jane Doe",
        "relationship": "Spouse",
        "phone": "+1-555-123-4567",
        "email": "jane.doe@example.com",
        "priority": 1,
        "is_active": True
    }

    response = client.post("/emergency-contacts", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Jane Doe"
    assert data["relationship"] == "Spouse"
    assert data["phone"] == "+1-555-123-4567"
    assert data["email"] == "jane.doe@example.com"
    assert data["priority"] == 1
    assert data["family_member_id"] == family_member_id


def test_create_emergency_contact_guardian_with_full_access(client, auth_headers, test_user_id):
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
        "emergency_contacts": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "name": "Dr. Watson",
        "relationship": "Physician",
        "phone": "5559876543",
        "priority": 2
    }

    response = client.post("/emergency-contacts", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["name"] == "Dr. Watson"


def test_create_emergency_contact_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    # Read-only consent, cannot create contact
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
        "emergency_contacts": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "name": "Uncle Bob",
        "phone": "1234567890"
    }

    response = client.post("/emergency-contacts", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_create_emergency_contact_nonexistent_member(client, auth_headers):
    mock_db = setup_mock_supabase({"family_members": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": str(uuid.uuid4()),
        "name": "Aunt May",
        "phone": "9876543210"
    }

    response = client.post("/emergency-contacts", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Family member not found"


def test_create_emergency_contact_invalid_phone_and_email(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    # Invalid phone (letters only)
    res_phone = client.post(
        "/emergency-contacts",
        json={"family_member_id": family_member_id, "name": "Test", "phone": "invalid-phone"},
        headers=auth_headers
    )
    # Invalid email
    res_email = client.post(
        "/emergency-contacts",
        json={"family_member_id": family_member_id, "name": "Test", "phone": "12345678", "email": "not-an-email"},
        headers=auth_headers
    )

    app.dependency_overrides.clear()

    assert res_phone.status_code == 422
    assert res_email.status_code == 422


def test_list_emergency_contacts_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "name": "Grandpa Joe",
            "relationship": "Grandfather",
            "phone": "5551112222",
            "priority": 1,
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/emergency-contacts", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == contact_id
    assert data[0]["name"] == "Grandpa Joe"


def test_list_emergency_contacts_filtered_by_member(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "name": "Neighbor Alice",
            "phone": "5553334444",
            "priority": 3,
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency-contacts?family_member_id={family_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Neighbor Alice"


def test_list_emergency_contacts_forbidden_member(client, auth_headers, test_user_id):
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
        "emergency_contacts": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency-contacts?family_member_id={family_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_get_emergency_contact_by_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "name": "Local Clinic",
            "phone": "5557778888",
            "priority": 1,
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency-contacts/{contact_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == contact_id
    assert data["name"] == "Local Clinic"


def test_get_emergency_contact_not_found(client, auth_headers):
    mock_db = setup_mock_supabase({"emergency_contacts": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency-contacts/{uuid.uuid4()}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Emergency contact not found"


def test_get_emergency_contact_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "name": "Secret Contact",
            "phone": "5550001111",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/emergency-contacts/{contact_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_update_emergency_contact_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "name": "Jane Doe",
            "phone": "5551234567",
            "priority": 1,
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"phone": "+1-555-999-8888", "relationship": "Life Partner"}
    response = client.put(f"/emergency-contacts/{contact_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["phone"] == "+1-555-999-8888"
    assert data["relationship"] == "Life Partner"


def test_update_emergency_contact_guardian_read_only_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

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
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "name": "Contact X",
            "phone": "5551112222",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"name": "Hacked Name"}
    response = client.put(f"/emergency-contacts/{contact_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_update_emergency_contact_empty_payload_bad_request(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "name": "Jane",
            "phone": "5551112222",
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.put(f"/emergency-contacts/{contact_id}", json={}, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "No fields provided for update"


def test_delete_emergency_contact_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/emergency-contacts/{contact_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 204


def test_delete_emergency_contact_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    contact_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "emergency_contacts": [{
            "id": contact_id,
            "family_member_id": family_member_id,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/emergency-contacts/{contact_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unauthenticated_request_rejected(client):
    response = client.get("/emergency-contacts")
    assert response.status_code in (401, 403)
