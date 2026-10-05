from unittest.mock import MagicMock
from app.auth.dependencies import get_supabase
from app.main import app
import uuid


def test_create_family_api(client, auth_headers, test_user_id):
    mock_supabase = MagicMock()
    
    # Mock family creation insert result
    family_id = str(uuid.uuid4())
    mock_family_res = MagicMock()
    mock_family_res.data = [{
        "id": family_id,
        "name": "Smith Family",
        "description": "Family Health Group",
        "created_by": test_user_id,
        "created_at": "2026-10-05T19:40:00Z",
        "updated_at": "2026-10-05T19:40:00Z"
    }]

    # Mock member creation insert result
    mock_member_res = MagicMock()
    mock_member_res.data = [{
        "id": str(uuid.uuid4()),
        "family_id": family_id,
        "user_id": test_user_id,
        "role": "ADMIN",
        "joined_at": "2026-10-05T19:40:00Z"
    }]

    # Wire chain calls: supabase.table("families").insert(...).execute()
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.side_effect = [mock_family_res, mock_member_res]
    mock_supabase.table.return_value = mock_table

    app.dependency_overrides[get_supabase] = lambda: mock_supabase

    response = client.post(
        "/api/v1/families",
        json={"name": "Smith Family", "description": "Family Health Group"},
        headers=auth_headers
    )
    
    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Smith Family"
    assert data["id"] == family_id
    assert len(data["members"]) == 1
    assert data["members"][0]["role"] == "ADMIN"


def test_create_consent_api(client, auth_headers, test_user_id):
    mock_supabase = MagicMock()
    grantee_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    consent_id = str(uuid.uuid4())

    mock_consent_res = MagicMock()
    mock_consent_res.data = [{
        "id": consent_id,
        "granter_id": test_user_id,
        "grantee_id": grantee_id,
        "family_id": family_id,
        "permission_level": "READ_ONLY",
        "status": "PENDING",
        "notes": "Emergency view access",
        "created_at": "2026-10-05T19:40:00Z",
        "updated_at": "2026-10-05T19:40:00Z"
    }]

    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value = mock_consent_res
    mock_supabase.table.return_value = mock_table

    app.dependency_overrides[get_supabase] = lambda: mock_supabase

    response = client.post(
        "/api/v1/consents",
        json={
            "grantee_id": grantee_id,
            "family_id": family_id,
            "permission_level": "READ_ONLY",
            "notes": "Emergency view access"
        },
        headers=auth_headers
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PENDING"
    assert data["permission_level"] == "READ_ONLY"
