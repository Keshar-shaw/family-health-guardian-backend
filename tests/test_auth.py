import pytest
from app.auth.jwt import decode_jwt_token
from fastapi import HTTPException


def test_decode_jwt_token(valid_jwt_token, test_user_id):
    payload = decode_jwt_token(valid_jwt_token)
    assert payload.sub == test_user_id
    assert payload.email == "guardian_test@example.com"


def test_decode_invalid_jwt_token():
    with pytest.raises(HTTPException) as exc_info:
        decode_jwt_token("invalid.token.str")
    assert exc_info.value.status_code == 401


def test_protected_route_unauthenticated(client):
    response = client.get("/api/v1/profiles/me")
    assert response.status_code == 403 or response.status_code == 401
