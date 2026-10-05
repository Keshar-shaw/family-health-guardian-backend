import pytest
import io
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

    mock_bucket = MagicMock()
    mock_bucket.upload.return_value = {"Key": "test_path"}
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://storage.supabase.co/signed/test?token=abc"}
    mock_bucket.remove.return_value = [{"name": "test_path"}]
    mock_supabase.storage.from_.return_value = mock_bucket

    return mock_supabase


def test_upload_medical_report_pdf_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medical_reports": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    fake_pdf = io.BytesIO(b"%PDF-1.4 Fake PDF Content for Lab Report")
    files = {"file": ("blood_test.pdf", fake_pdf, "application/pdf")}
    data = {
        "family_member_id": family_member_id,
        "report_type": "LAB_REPORT",
        "description": "Comprehensive Metabolic Panel"
    }

    response = client.post("/medical-reports", files=files, data=data, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    res_data = response.json()
    assert res_data["file_name"] == "blood_test.pdf"
    assert res_data["mime_type"] == "application/pdf"
    assert res_data["report_type"] == "LAB_REPORT"
    assert res_data["download_url"] is not None
    assert "token=abc" in res_data["download_url"]


def test_upload_medical_report_png_image(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medical_reports": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    fake_png = io.BytesIO(b"\x89PNG\r\n\x1a\nFake PNG Bytes")
    files = {"file": ("chest_xray.png", fake_png, "image/png")}
    data = {
        "family_member_id": family_member_id,
        "report_type": "IMAGING_SCAN",
        "description": "Chest X-Ray scan"
    }

    response = client.post("/medical-reports", files=files, data=data, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["file_name"] == "chest_xray.png"
    assert response.json()["report_type"] == "IMAGING_SCAN"


def test_upload_medical_report_guardian_with_full_access(client, auth_headers, test_user_id):
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
        "medical_reports": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    fake_jpg = io.BytesIO(b"\xff\xd8\xffFake JPEG Bytes")
    files = {"file": ("rx_slip.jpg", fake_jpg, "image/jpeg")}
    data = {
        "family_member_id": family_member_id,
        "report_type": "PRESCRIPTION"
    }

    response = client.post("/medical-reports", files=files, data=data, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["file_name"] == "rx_slip.jpg"


def test_upload_medical_report_invalid_file_type_rejected(client, auth_headers, test_user_id):
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

    fake_txt = io.BytesIO(b"Unauthorized text file content")
    files = {"file": ("report.txt", fake_txt, "text/plain")}
    data = {"family_member_id": family_member_id}

    response = client.post("/medical-reports", files=files, data=data, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


def test_upload_medical_report_unauthorized_member_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": []
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    fake_pdf = io.BytesIO(b"%PDF Fake")
    files = {"file": ("report.pdf", fake_pdf, "application/pdf")}
    data = {"family_member_id": family_member_id}

    response = client.post("/medical-reports", files=files, data=data, headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_list_medical_reports_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medical_reports": [{
            "id": report_id,
            "family_member_id": family_member_id,
            "uploaded_by": test_user_id,
            "file_name": "mri_scan.pdf",
            "storage_path": f"{family_member_id}/mri_scan.pdf",
            "report_type": "IMAGING_SCAN",
            "mime_type": "application/pdf",
            "file_size": 2048,
            "report_date": "2026-10-06",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get("/medical-reports", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == report_id
    assert data[0]["file_name"] == "mri_scan.pdf"
    assert data[0]["download_url"] is not None


def test_get_medical_report_by_id(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medical_reports": [{
            "id": report_id,
            "family_member_id": family_member_id,
            "uploaded_by": test_user_id,
            "file_name": "ultrasound.jpg",
            "storage_path": f"{family_member_id}/ultrasound.jpg",
            "report_type": "IMAGING_SCAN",
            "mime_type": "image/jpeg",
            "file_size": 4096,
            "report_date": "2026-10-06",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medical-reports/{report_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == report_id
    assert data["file_name"] == "ultrasound.jpg"
    assert data["download_url"] is not None


def test_get_medical_report_not_found(client, auth_headers):
    mock_db = setup_mock_supabase({"medical_reports": []})

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.get(f"/medical-reports/{uuid.uuid4()}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Medical report not found"


def test_delete_medical_report_self(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "medical_reports": [{
            "id": report_id,
            "family_member_id": family_member_id,
            "storage_path": "path/to/file.pdf",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/medical-reports/{report_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 204


def test_delete_medical_report_unauthorized_forbidden(client, auth_headers, test_user_id):
    family_member_id = str(uuid.uuid4())
    other_patient_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    mock_db = setup_mock_supabase({
        "family_members": [{
            "id": family_member_id,
            "family_id": str(uuid.uuid4()),
            "user_id": other_patient_id,
            "role": "MEMBER"
        }],
        "consents": [],
        "medical_reports": [{
            "id": report_id,
            "family_member_id": family_member_id,
            "storage_path": "path/to/file.pdf",
            "created_at": "2026-10-06T00:00:00Z"
        }]
    })

    app.dependency_overrides[get_supabase] = lambda: mock_db

    response = client.delete(f"/medical-reports/{report_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert response.status_code == 403


def test_unauthenticated_request_rejected(client):
    response = client.get("/medical-reports")
    assert response.status_code in (401, 403)
