import pytest
import jwt
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_user_id():
    return str(uuid.uuid4())


@pytest.fixture
def valid_jwt_token(test_user_id):
    payload = {
        "sub": test_user_id,
        "email": "guardian_test@example.com",
        "role": "authenticated",
        "aud": "authenticated"
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def auth_headers(valid_jwt_token):
    return {"Authorization": f"Bearer {valid_jwt_token}"}
