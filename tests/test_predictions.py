from unittest.mock import patch, MagicMock


def test_diabetes_metadata_endpoint(client):
    response = client.get("/api/v1/predictions/diabetes/metadata")
    assert response.status_code == 200
    data = response.json()
    assert data["model_name"] == "RandomForestClassifier"
    assert data["features_count"] == 13
    assert "expected_features" in data
    assert "age" in data["expected_features"]
    assert "blood_glucose_level" in data["expected_features"]


def test_predict_diabetes_high_risk(client, auth_headers):
    payload = {
        "age": 60.0,
        "gender": "Male",
        "hypertension": True,
        "heart_disease": True,
        "smoking_history": "former",
        "bmi": 32.5,
        "hba1c_level": 7.5,
        "blood_glucose_level": 180.0
    }
    with patch("app.services.audit.AuditService.log_action"):
        response = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "prediction" in data
        assert data["risk_label"] in ("High Risk", "Low Risk")
        assert 0.0 <= data["risk_probability"] <= 1.0
        assert 0.0 <= data["risk_percentage"] <= 100.0
        assert "recommendations" in data
        assert len(data["recommendations"]) > 0


def test_predict_diabetes_low_risk(client, auth_headers):
    payload = {
        "age": 22.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 21.0,
        "hba1c_level": 4.5,
        "blood_glucose_level": 85.0
    }
    with patch("app.services.audit.AuditService.log_action"):
        response = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["prediction"] == 0
        assert data["risk_label"] == "Low Risk"
        assert data["risk_percentage"] < 30.0


def test_predict_diabetes_unauthorized(client):
    payload = {
        "age": 45.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.0,
        "hba1c_level": 5.2,
        "blood_glucose_level": 95.0
    }
    response = client.post("/api/v1/predictions/diabetes", json=payload)
    assert response.status_code == 401


def test_predict_diabetes_validation_error(client, auth_headers):
    invalid_payload = {
        "age": 150.0,  # exceeds ge=0, le=120
        "gender": "InvalidGender",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 5.0,  # below ge=10.0
        "hba1c_level": 25.0,  # exceeds le=20.0
        "blood_glucose_level": 800.0  # exceeds le=600.0
    }
    response = client.post("/api/v1/predictions/diabetes", json=invalid_payload, headers=auth_headers)
    assert response.status_code == 422
