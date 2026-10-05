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
        p.setdefault("is_active", True)
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


def test_create_medicine_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "medicine_name": "Amoxicillin",
        "dosage": "500",
        "dosage_unit": "mg",
        "frequency": "Three times daily",
        "route": "Oral",
        "start_date": "2026-10-01",
        "end_date": "2026-10-10",
        "prescribed_by": "Dr. Smith",
        "instructions": "Take with meals",
        "is_active": True
    }

    response = client.post("/medicines", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["medicine_name"] == "Amoxicillin"
    assert data["dosage"] == "500"
    assert data["dosage_unit"] == "mg"
    assert data["family_member_id"] == family_member_id
    assert data["is_active"] is True


def test_create_medicine_guardian_with_full_access(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
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
        "medicines": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "medicine_name": "Metformin",
        "dosage": "850",
        "dosage_unit": "mg",
        "frequency": "Twice daily",
        "instructions": "Take after breakfast and dinner"
    }

    response = client.post("/medicines", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["medicine_name"] == "Metformin"


def test_create_medicine_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    # Only READ_ONLY consent, not FULL_ACCESS
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
        "medicines": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": family_member_id,
        "medicine_name": "Lisinopril",
        "dosage": "10",
        "dosage_unit": "mg"
    }

    response = client.post("/medicines", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_create_medicine_nonexistent_member(client, auth_headers):
    mock_db = setup_mock_supabase({"family_members": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "family_member_id": str(uuid.uuid4()),
        "medicine_name": "Aspirin"
    }

    response = client.post("/medicines", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Family member not found"


def test_list_medicines_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Atorvastatin",
            "dosage": "20",
            "dosage_unit": "mg",
            "frequency": "Once daily",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/medicines", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == med_id
    assert data[0]["medicine_name"] == "Atorvastatin"


def test_list_medicines_filtered_by_member(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Ibuprofen",
            "dosage": "400",
            "dosage_unit": "mg",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicines?family_member_id={family_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["medicine_name"] == "Ibuprofen"


def test_list_medicines_filtered_by_member_forbidden(client, auth_headers, test_user_id):
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
        "medicines": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicines?family_member_id={family_member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_get_medicine_by_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Paracetamol",
            "dosage": "650",
            "dosage_unit": "mg",
            "frequency": "As needed",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicines/{med_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == med_id
    assert data["medicine_name"] == "Paracetamol"


def test_get_medicine_not_found(client, auth_headers):
    mock_db = setup_mock_supabase({"medicines": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicines/{uuid.uuid4()}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Medicine record not found"


def test_get_medicine_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Omeprazole",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medicines/{med_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_update_medicine_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Levothyroxine",
            "dosage": "50",
            "dosage_unit": "mcg",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"dosage": "75", "instructions": "Take 30 mins before breakfast"}
    response = client.put(f"/medicines/{med_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["dosage"] == "75"
    assert data["instructions"] == "Take 30 mins before breakfast"


def test_update_medicine_guardian_read_only_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    patient_user_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    # Read-only consent should not allow updating medicines
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
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Vitamin D3",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {"dosage": "2000"}
    response = client.put(f"/medicines/{med_id}", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_update_medicine_empty_payload_bad_request(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Cetirizine",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.put(f"/medicines/{med_id}", json={}, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "No fields provided for update"


def test_delete_medicine_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Amoxicillin",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/medicines/{med_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 204


def test_delete_medicine_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    med_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medicines": [{
            "id": med_id,
            "family_member_id": family_member_id,
            "medicine_name": "Ciprofloxacin",
            "is_active": True,
            "created_at": "2026-10-06T00:00:00Z",
            "updated_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/medicines/{med_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unauthenticated_request_rejected(client):
    response = client.get("/medicines")
    assert response.status_code in (401, 403)
