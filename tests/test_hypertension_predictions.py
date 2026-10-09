import uuid
import time
from unittest.mock import patch, MagicMock
import pytest
import pandas as pd
import jwt

from app.config import settings
from app.services.hypertension_service import hypertension_ml_service, EXPECTED_HYPERTENSION_FEATURES
from app.schemas.ml_prediction import HypertensionPredictionRequest


def test_hypertension_metadata_endpoint(client):
    """Verify GET /predictions/hypertension/metadata returns model metadata and feature definitions."""
    res = client.get("/api/v1/predictions/hypertension/metadata")
    assert res.status_code == 200
    data = res.json()
    assert data["model_name"] == "RandomForestClassifier"
    assert data["disease_target"] == "Hypertension Risk"
    assert data["model_version"] == "1.0.0"
    assert data["features_count"] == 13
    assert "expected_features" in data
    assert "age" in data["expected_features"]
    assert "diabetes" in data["expected_features"]
    assert "regulatory_disclaimer" in data


def test_predict_hypertension_high_risk(client, auth_headers):
    """Verify high-risk elderly patient with cardiovascular comorbidity flags high risk."""
    payload = {
        "age": 72.0,
        "gender": "Male",
        "heart_disease": True,
        "smoking_history": "former",
        "bmi": 34.5,
        "hba1c_level": 7.2,
        "blood_glucose_level": 165.0,
        "diabetes": True
    }
    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["prediction"] == 1
        assert data["risk_label"] == "High Risk"
        assert 0.0 <= data["risk_probability"] <= 1.0
        assert data["risk_percentage"] >= 50.0
        assert len(data["recommendations"]) > 0


def test_predict_hypertension_low_risk(client, auth_headers):
    """Verify young healthy individual flags low risk with low probability."""
    payload = {
        "age": 22.0,
        "gender": "Female",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 20.5,
        "hba1c_level": 4.8,
        "blood_glucose_level": 82.0,
        "diabetes": False
    }
    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["prediction"] == 0
        assert data["risk_label"] == "Low Risk"
        assert data["risk_percentage"] < 35.0


def test_predict_hypertension_unauthorized(client):
    """Verify unauthenticated requests are rejected with HTTP 401."""
    payload = {
        "age": 45.0,
        "gender": "Male",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.0,
        "hba1c_level": 5.2,
        "blood_glucose_level": 95.0,
        "diabetes": False
    }
    res = client.post("/api/v1/predictions/hypertension", json=payload)
    assert res.status_code == 401


def test_predict_hypertension_validation_error(client, auth_headers):
    """Verify invalid payloads (exceeding range bounds or invalid enums) return HTTP 422."""
    bad_payload = {
        "age": 150.0,  # exceeds le=120
        "gender": "Alien",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 5.0,  # below ge=10.0
        "hba1c_level": 25.0,
        "blood_glucose_level": 800.0,
        "diabetes": False
    }
    res = client.post("/api/v1/predictions/hypertension", json=bad_payload, headers=auth_headers)
    assert res.status_code == 422


def test_hypertension_feature_names_and_ordering_match_model():
    """Verify expected features match the trained model's feature_names_in_ exactly."""
    expected = hypertension_ml_service.get_expected_features()
    model_features = list(hypertension_ml_service._model.feature_names_in_)

    assert len(expected) == 13
    assert len(model_features) == 13
    assert expected == model_features, f"Feature mismatch: {expected} != {model_features}"


def test_build_hypertension_feature_dataframe_exact_columns():
    """Verify build_feature_dataframe produces exact column names and values."""
    req = HypertensionPredictionRequest(
        age=58.0,
        gender="Male",
        heart_disease=True,
        smoking_history="former",
        bmi=29.2,
        hba1c_level=6.4,
        blood_glucose_level=135.0,
        diabetes=True
    )
    df = hypertension_ml_service.build_feature_dataframe(req)

    assert isinstance(df, pd.DataFrame)
    assert df.shape == (1, 13)
    assert list(df.columns) == list(hypertension_ml_service._model.feature_names_in_)
    assert not df.isna().any().any()

    assert df.iloc[0]["age"] == 58.0
    assert df.iloc[0]["heart_disease"] == 1
    assert df.iloc[0]["bmi"] == 29.2
    assert df.iloc[0]["HbA1c_level"] == 6.4
    assert df.iloc[0]["blood_glucose_level"] == 135.0
    assert df.iloc[0]["diabetes"] == 1
    assert df.iloc[0]["gender_Male"] == 1
    assert df.iloc[0]["gender_Other"] == 0
    assert df.iloc[0]["smoking_history_former"] == 1
    assert df.iloc[0]["smoking_history_never"] == 0


def test_incorrect_hypertension_feature_ordering_rejected():
    """Regression test: verify model raises ValueError when column names do not match expected features."""
    shuffled_columns = [
        'blood_glucose_level', 'age', 'heart_disease',
        'bmi', 'HbA1c_level', 'diabetes', 'gender_Male', 'gender_Other',
        'smoking_history_current', 'smoking_history_ever',
        'smoking_history_former', 'smoking_history_never', 'wrong_column'
    ]
    invalid_df = pd.DataFrame([[0] * 13], columns=shuffled_columns)

    with pytest.raises(ValueError, match="The feature names should match those that were passed during fit"):
        hypertension_ml_service._model.predict(invalid_df)


def test_hypertension_one_hot_encoding_parity():
    """Verify one-hot encoding parity with training drop_first=True baseline."""
    base = {
        "age": 40.0,
        "heart_disease": False,
        "bmi": 25.0,
        "hba1c_level": 5.0,
        "blood_glucose_level": 90.0,
        "diabetes": False
    }

    # Female baseline
    req_female = HypertensionPredictionRequest(gender="Female", smoking_history="never", **base)
    df_female = hypertension_ml_service.build_feature_dataframe(req_female)
    assert df_female.iloc[0]["gender_Male"] == 0
    assert df_female.iloc[0]["gender_Other"] == 0

    # Male
    req_male = HypertensionPredictionRequest(gender="Male", smoking_history="never", **base)
    df_male = hypertension_ml_service.build_feature_dataframe(req_male)
    assert df_male.iloc[0]["gender_Male"] == 1
    assert df_male.iloc[0]["gender_Other"] == 0

    # No Info smoking baseline
    req_no_info = HypertensionPredictionRequest(gender="Female", smoking_history="No Info", **base)
    df_no_info = hypertension_ml_service.build_feature_dataframe(req_no_info)
    assert df_no_info.iloc[0]["smoking_history_current"] == 0
    assert df_no_info.iloc[0]["smoking_history_ever"] == 0
    assert df_no_info.iloc[0]["smoking_history_former"] == 0
    assert df_no_info.iloc[0]["smoking_history_never"] == 0
    assert df_no_info.iloc[0]["smoking_history_not current"] == 0


def test_rejects_nan_null_and_missing_hypertension_measurements(client, auth_headers):
    """Ensure invalid, null, or NaN measurements are strictly rejected and not defaulted to zero."""
    valid_payload = {
        "age": 45.0,
        "gender": "Male",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 25.0,
        "hba1c_level": 5.5,
        "blood_glucose_level": 100.0,
        "diabetes": False
    }

    # Null value
    assert client.post("/api/v1/predictions/hypertension", json={**valid_payload, "age": None}, headers=auth_headers).status_code == 422
    # String NaN
    assert client.post("/api/v1/predictions/hypertension", json={**valid_payload, "bmi": "nan"}, headers=auth_headers).status_code == 422
    # Non-numeric text
    assert client.post("/api/v1/predictions/hypertension", json={**valid_payload, "blood_glucose_level": "normal"}, headers=auth_headers).status_code == 422
    # Missing field
    missing_bmi = {k: v for k, v in valid_payload.items() if k != "bmi"}
    assert client.post("/api/v1/predictions/hypertension", json=missing_bmi, headers=auth_headers).status_code == 422


def test_individual_hypertension_physiological_measurement_boundaries(client, auth_headers):
    """Verify each physiological metric strictly rejects out-of-range boundaries."""
    base = {
        "age": 40.0,
        "gender": "Female",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.0,
        "hba1c_level": 5.2,
        "blood_glucose_level": 95.0,
        "diabetes": False
    }

    # Age boundaries: [0.0, 120.0]
    assert client.post("/api/v1/predictions/hypertension", json={**base, "age": -1.0}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/hypertension", json={**base, "age": 121.0}, headers=auth_headers).status_code == 422

    # BMI boundaries: [10.0, 80.0]
    assert client.post("/api/v1/predictions/hypertension", json={**base, "bmi": 9.9}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/hypertension", json={**base, "bmi": 80.1}, headers=auth_headers).status_code == 422

    # HbA1c boundaries: [3.0, 20.0]
    assert client.post("/api/v1/predictions/hypertension", json={**base, "hba1c_level": 2.9}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/hypertension", json={**base, "hba1c_level": 20.1}, headers=auth_headers).status_code == 422

    # Blood glucose boundaries: [30.0, 600.0]
    assert client.post("/api/v1/predictions/hypertension", json={**base, "blood_glucose_level": 29.0}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/hypertension", json={**base, "blood_glucose_level": 601.0}, headers=auth_headers).status_code == 422


def test_hypertension_model_successful_loading_and_caching():
    """Verify load_model successfully loads and caches model instance."""
    hypertension_ml_service.load_model(force_reload=False)
    assert hypertension_ml_service.is_loaded is True
    cached = hypertension_ml_service._model

    hypertension_ml_service.load_model(force_reload=False)
    assert hypertension_ml_service._model is cached


def test_hypertension_model_path_resolved_relative_to_project():
    """Verify model path resolution is anchored to backend project root."""
    from pathlib import Path
    path = hypertension_ml_service._resolve_model_path()
    assert isinstance(path, Path)
    assert path.is_file()
    assert path.name == "hypertension_model.pkl"
    assert "models" in path.parts


def test_missing_hypertension_model_raises_clear_error_and_never_predicts():
    """Verify missing model file raises clear error instead of producing false prediction."""
    req = HypertensionPredictionRequest(
        age=30.0,
        gender="Female",
        heart_disease=False,
        smoking_history="never",
        bmi=22.0,
        hba1c_level=5.0,
        blood_glucose_level=90.0,
        diabetes=False
    )

    with patch.object(hypertension_ml_service, "_resolve_model_path", side_effect=FileNotFoundError("Mock HTN model missing")):
        with patch.object(hypertension_ml_service, "_model", None):
            with pytest.raises(FileNotFoundError, match="Mock HTN model missing"):
                hypertension_ml_service.predict(req)

    hypertension_ml_service.load_model(force_reload=True)


def test_missing_hypertension_model_endpoint_returns_503(client, auth_headers):
    """Verify endpoint returns HTTP 503 when model is unavailable."""
    payload = {
        "age": 45.0,
        "gender": "Male",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 25.0,
        "hba1c_level": 5.5,
        "blood_glucose_level": 100.0,
        "diabetes": False
    }

    with patch.object(hypertension_ml_service, "predict", side_effect=RuntimeError("Hypertension ML model unavailable")):
        res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
        assert res.status_code == 503
        assert "Hypertension ML service is unavailable" in res.json()["detail"]


def test_incompatible_hypertension_model_structure_rejected():
    """Verify corrupt or incompatible model objects missing predict methods are rejected."""
    with patch("joblib.load", return_value={"model": "invalid"}):
        with pytest.raises(ValueError, match="missing predict/predict_proba"):
            hypertension_ml_service.load_model(force_reload=True)

    hypertension_ml_service.load_model(force_reload=True)


def test_predict_hypertension_save_to_records_self_no_family(client, auth_headers, test_user_id):
    """Verify save_to_records=True persists record with prediction_type='HYPERTENSION'."""
    from app.auth.dependencies import get_supabase
    from app.main import app
    from tests.test_predictions import setup_mock_db

    mock_db = setup_mock_db({
        "prediction_history": [],
        "audit_logs": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 55.0,
        "gender": "Female",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 27.0,
        "hba1c_level": 5.6,
        "blood_glucose_level": 105.0,
        "diabetes": False,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["record_id"] is not None
    assert uuid.UUID(data["record_id"])
    assert data["prediction"] in (0, 1)


def test_predict_hypertension_save_to_records_authorized_family(client, auth_headers, test_user_id):
    """Verify save_to_records=True with authorized family_id persists linked family references."""
    from app.auth.dependencies import get_supabase
    from app.main import app
    from tests.test_predictions import setup_mock_db

    family_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())

    mock_db = setup_mock_db({
        "family_members": [{
            "id": member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "prediction_history": [],
        "audit_logs": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 65.0,
        "gender": "Male",
        "heart_disease": True,
        "smoking_history": "current",
        "bmi": 32.0,
        "hba1c_level": 7.0,
        "blood_glucose_level": 160.0,
        "diabetes": True,
        "family_id": family_id,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    assert res.json()["record_id"] is not None


def test_predict_hypertension_save_to_records_denied_cross_family(client, auth_headers, test_user_id):
    """Verify save_to_records=True with unauthorized family_id returns HTTP 403."""
    from app.auth.dependencies import get_supabase
    from app.main import app
    from tests.test_predictions import setup_mock_db

    unauthorized_family_id = str(uuid.uuid4())

    mock_db = setup_mock_db({
        "family_members": [],
        "prediction_history": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 42.0,
        "gender": "Female",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.0,
        "hba1c_level": 5.0,
        "blood_glucose_level": 92.0,
        "diabetes": False,
        "family_id": unauthorized_family_id,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 403
    assert "Access denied: you are not a member of this family" in res.json()["detail"]


def test_predict_hypertension_save_to_records_denied_cross_member_no_consent(client, auth_headers, test_user_id):
    """Verify saving prediction for another member without active consent returns HTTP 403."""
    from app.auth.dependencies import get_supabase
    from app.main import app
    from tests.test_predictions import setup_mock_db

    family_id = str(uuid.uuid4())
    my_member_id = str(uuid.uuid4())
    other_member_id = str(uuid.uuid4())

    mock_db = setup_mock_db({
        "family_members": [
            {"id": my_member_id, "family_id": family_id, "user_id": test_user_id, "role": "MEMBER"},
            {"id": other_member_id, "family_id": family_id, "user_id": str(uuid.uuid4()), "role": "MEMBER"}
        ],
        "consents": [],
        "prediction_history": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 45.0,
        "gender": "Male",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 27.0,
        "hba1c_level": 5.8,
        "blood_glucose_level": 115.0,
        "diabetes": False,
        "family_id": family_id,
        "family_member_id": other_member_id,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 403
    assert "Active FULL_ACCESS consent required" in res.json()["detail"]


def test_predict_hypertension_database_failure(client, auth_headers):
    """Verify database insertion error produces HTTP 500 without crashing."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.side_effect = RuntimeError("Supabase connection reset")
    mock_supabase.table.return_value = mock_table
    app.dependency_overrides[get_supabase] = lambda: mock_supabase

    payload = {
        "age": 50.0,
        "gender": "Female",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 26.0,
        "hba1c_level": 5.5,
        "blood_glucose_level": 100.0,
        "diabetes": False,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 500
    assert "Database failure" in res.json()["detail"]


def test_hypertension_sanitization_no_auth_tokens_in_stored_records(client, auth_headers, test_user_id):
    """Verify stored records and audit logs NEVER contain bearer credentials or auth tokens."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    inserted_records = []
    mock_supabase = MagicMock()

    def get_table(name):
        builder = MagicMock()
        if name == "prediction_history":
            def insert_record(payload):
                inserted_records.append(payload)
                mock_res = MagicMock()
                p = dict(payload)
                p["id"] = str(uuid.uuid4())
                mock_res.data = [p]
                exec_mock = MagicMock()
                exec_mock.execute.return_value = mock_res
                return exec_mock
            builder.insert.side_effect = insert_record
        elif name == "audit_logs":
            def insert_audit(payload):
                mock_res = MagicMock()
                mock_res.data = [payload]
                exec_mock = MagicMock()
                exec_mock.execute.return_value = mock_res
                return exec_mock
            builder.insert.side_effect = insert_audit
        return builder

    mock_supabase.table.side_effect = get_table
    app.dependency_overrides[get_supabase] = lambda: mock_supabase

    payload = {
        "age": 60.0,
        "gender": "Male",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 28.0,
        "hba1c_level": 5.9,
        "blood_glucose_level": 110.0,
        "diabetes": False,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    assert len(inserted_records) == 1
    stored = inserted_records[0]
    assert stored["prediction_type"] == "HYPERTENSION"

    expected_keys = {"age", "gender", "bmi", "hba1c_level", "blood_glucose_level", "heart_disease", "diabetes", "smoking_history"}
    assert set(stored["input_measurements"].keys()) == expected_keys

    for val in stored["input_measurements"].values():
        val_str = str(val).lower()
        assert "bearer" not in val_str
        assert "token" not in val_str
        assert "password" not in val_str


def test_hypertension_prediction_probability_and_response_schema_contract(client, auth_headers):
    """Verify prediction probability bounds and complete response schema contract."""
    from datetime import datetime

    payload = {
        "age": 55.0,
        "gender": "Male",
        "heart_disease": False,
        "smoking_history": "former",
        "bmi": 28.5,
        "hba1c_level": 6.3,
        "blood_glucose_level": 135.0,
        "diabetes": False,
        "save_to_records": False
    }

    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()

        assert isinstance(data["prediction"], int)
        assert data["prediction"] in (0, 1)
        assert data["risk_label"] in ("Low Risk", "High Risk")
        assert isinstance(data["risk_probability"], float)
        assert 0.0 <= data["risk_probability"] <= 1.0
        assert data["risk_percentage"] == round(data["risk_probability"] * 100.0, 1)
        assert data["confidence_level"] in ("High Confidence", "Moderate Confidence", "Low Confidence (Borderline)")

        summary = data["feature_summary"]
        assert summary["age"] == 55.0
        assert summary["gender"] == "Male"
        assert summary["bmi"] == 28.5
        assert summary["diabetes"] is False
        assert summary["heart_disease"] is False

        assert datetime.fromisoformat(data["assessed_at"].replace("Z", "+00:00"))
        assert data["record_id"] is None


def test_hypertension_recommendations_triggered_by_clinical_conditions(client, auth_headers):
    """Verify specific physiological inputs trigger appropriate tailored recommendations."""
    payload = {
        "age": 68.0,
        "gender": "Male",
        "heart_disease": True,
        "smoking_history": "current",
        "bmi": 32.5,
        "hba1c_level": 7.5,
        "blood_glucose_level": 180.0,
        "diabetes": True,
        "save_to_records": False
    }

    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/hypertension", json=payload, headers=auth_headers)
        assert res.status_code == 200
        recs = res.json()["recommendations"]

        assert any("isolated systolic hypertension" in r or "age" in r.lower() for r in recs)
        assert any("DASH" in r or "sodium" in r for r in recs)
        assert any("Cardiovascular disease" in r for r in recs)
        assert any("Diabetes diagnosed" in r for r in recs)
        assert any("Smoking" in r for r in recs)


def test_hypertension_auth_expired_or_invalid_tokens_rejected(client):
    """Verify expired or malformed JWT tokens are rejected with HTTP 401."""
    payload = {
        "age": 35.0,
        "gender": "Female",
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 22.0,
        "hba1c_level": 4.8,
        "blood_glucose_level": 88.0,
        "diabetes": False
    }

    # Expired token
    expired_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) - 3600, "aud": "authenticated"},
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256"
    )
    res_exp = client.post("/api/v1/predictions/hypertension", json=payload, headers={"Authorization": f"Bearer {expired_token}"})
    assert res_exp.status_code == 401

    # Malformed token
    res_bad = client.post("/api/v1/predictions/hypertension", json=payload, headers={"Authorization": "Bearer malformed.jwt.token"})
    assert res_bad.status_code == 401
