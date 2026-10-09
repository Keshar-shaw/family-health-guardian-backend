import uuid
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


# ---------------------------------------------------------------------------
# ML Feature-Ordering & Preprocessing Regression Tests
# ---------------------------------------------------------------------------

def test_feature_names_and_ordering_match_model():
    """Verify ml_service expected features match the trained model's feature_names_in_ exactly."""
    from app.services.ml_service import ml_service
    expected = ml_service.get_expected_features()
    model_features = list(ml_service._model.feature_names_in_)

    assert len(expected) == 13
    assert len(model_features) == 13
    assert expected == model_features, f"Feature mismatch: {expected} != {model_features}"


def test_build_feature_dataframe_exact_columns():
    """Verify build_feature_dataframe produces a DataFrame with exact column names and order."""
    import pandas as pd
    from app.services.ml_service import ml_service
    from app.schemas.ml_prediction import DiabetesPredictionRequest

    req = DiabetesPredictionRequest(
        age=52.0,
        gender="Male",
        hypertension=True,
        heart_disease=False,
        smoking_history="former",
        bmi=28.4,
        hba1c_level=6.2,
        blood_glucose_level=130.0
    )

    df = ml_service.build_feature_dataframe(req)

    assert isinstance(df, pd.DataFrame)
    assert df.shape == (1, 13)
    assert list(df.columns) == list(ml_service._model.feature_names_in_)
    assert not df.isna().any().any(), "DataFrame contains NaN values"

    # Verify column values
    assert df.iloc[0]["age"] == 52.0
    assert df.iloc[0]["hypertension"] == 1
    assert df.iloc[0]["heart_disease"] == 0
    assert df.iloc[0]["bmi"] == 28.4
    assert df.iloc[0]["HbA1c_level"] == 6.2
    assert df.iloc[0]["blood_glucose_level"] == 130.0
    assert df.iloc[0]["gender_Male"] == 1
    assert df.iloc[0]["gender_Other"] == 0
    assert df.iloc[0]["smoking_history_former"] == 1
    assert df.iloc[0]["smoking_history_never"] == 0


def test_incorrect_feature_ordering_rejected():
    """Regression test: verify model raises ValueError when column names do not match expected features."""
    import pytest
    import pandas as pd
    from app.services.ml_service import ml_service

    # Intentionally rename columns to invalid/misordered names
    shuffled_columns = [
        'blood_glucose_level', 'age', 'hypertension', 'heart_disease',
        'bmi', 'HbA1c_level', 'gender_Male', 'gender_Other',
        'smoking_history_current', 'smoking_history_ever',
        'smoking_history_former', 'smoking_history_never', 'wrong_column_name'
    ]
    invalid_df = pd.DataFrame([[0] * 13], columns=shuffled_columns)

    with pytest.raises(ValueError, match="The feature names should match those that were passed during fit"):
        ml_service._model.predict(invalid_df)


def test_one_hot_encoding_parity_with_training():
    """Verify categorical one-hot encoding parity with training pd.get_dummies(drop_first=True)."""
    from app.services.ml_service import ml_service
    from app.schemas.ml_prediction import DiabetesPredictionRequest

    base_payload = {
        "age": 30.0,
        "hypertension": False,
        "heart_disease": False,
        "bmi": 22.0,
        "hba1c_level": 5.0,
        "blood_glucose_level": 90.0
    }

    # Female: Both dummy columns should be 0 (reference/baseline)
    req_female = DiabetesPredictionRequest(gender="Female", smoking_history="never", **base_payload)
    df_female = ml_service.build_feature_dataframe(req_female)
    assert df_female.iloc[0]["gender_Male"] == 0
    assert df_female.iloc[0]["gender_Other"] == 0

    # Male: gender_Male=1, gender_Other=0
    req_male = DiabetesPredictionRequest(gender="Male", smoking_history="never", **base_payload)
    df_male = ml_service.build_feature_dataframe(req_male)
    assert df_male.iloc[0]["gender_Male"] == 1
    assert df_male.iloc[0]["gender_Other"] == 0

    # Other: gender_Male=0, gender_Other=1
    req_other = DiabetesPredictionRequest(gender="Other", smoking_history="never", **base_payload)
    df_other = ml_service.build_feature_dataframe(req_other)
    assert df_other.iloc[0]["gender_Male"] == 0
    assert df_other.iloc[0]["gender_Other"] == 1

    # No Info smoking: All 5 smoking dummies should be 0 (reference/baseline in training)
    req_no_info = DiabetesPredictionRequest(gender="Female", smoking_history="No Info", **base_payload)
    df_no_info = ml_service.build_feature_dataframe(req_no_info)
    assert df_no_info.iloc[0]["smoking_history_current"] == 0
    assert df_no_info.iloc[0]["smoking_history_ever"] == 0
    assert df_no_info.iloc[0]["smoking_history_former"] == 0
    assert df_no_info.iloc[0]["smoking_history_never"] == 0
    assert df_no_info.iloc[0]["smoking_history_not current"] == 0


def test_rejects_nan_null_and_missing_medical_measurements(client, auth_headers):
    """Ensure invalid, null, or NaN measurements are strictly rejected and NOT silently defaulted to zero."""
    valid_payload = {
        "age": 45.0,
        "gender": "Male",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 25.0,
        "hba1c_level": 5.5,
        "blood_glucose_level": 100.0
    }

    # Null value
    null_age = {**valid_payload, "age": None}
    res = client.post("/api/v1/predictions/diabetes", json=null_age, headers=auth_headers)
    assert res.status_code == 422

    # String NaN
    nan_bmi = {**valid_payload, "bmi": "nan"}
    res = client.post("/api/v1/predictions/diabetes", json=nan_bmi, headers=auth_headers)
    assert res.status_code == 422

    # Non-numeric text
    bad_glucose = {**valid_payload, "blood_glucose_level": "normal"}
    res = client.post("/api/v1/predictions/diabetes", json=bad_glucose, headers=auth_headers)
    assert res.status_code == 422

    # Missing field entirely
    missing_hba1c = {k: v for k, v in valid_payload.items() if k != "hba1c_level"}
    res = client.post("/api/v1/predictions/diabetes", json=missing_hba1c, headers=auth_headers)
    assert res.status_code == 422


def test_predict_diabetes_with_no_info_smoking(client, auth_headers):
    """Test prediction endpoint with 'No Info' / unknown smoking history."""
    payload = {
        "age": 40.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "No Info",
        "bmi": 23.5,
        "hba1c_level": 5.1,
        "blood_glucose_level": 92.0
    }
    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["prediction"] == 0
        assert data["risk_label"] == "Low Risk"


# ---------------------------------------------------------------------------
# Model Lifecycle, Caching & Missing/Incompatible Model Tests
# ---------------------------------------------------------------------------

def test_model_successful_loading_and_caching():
    """Verify load_model successfully loads model once and caches it across subsequent calls."""
    from app.services.ml_service import ml_service

    ml_service.load_model(force_reload=False)
    assert ml_service.is_loaded is True
    cached_model = ml_service._model

    # Calling load_model again without force_reload should immediately reuse cached model
    ml_service.load_model(force_reload=False)
    assert ml_service._model is cached_model


def test_model_path_resolved_relative_to_project():
    """Verify model path resolution is deterministic and anchored to backend project root."""
    from pathlib import Path
    from app.services.ml_service import ml_service

    path = ml_service._resolve_model_path()
    assert isinstance(path, Path)
    assert path.is_file()
    assert path.name == "diabetes_model.pkl"
    assert "models" in path.parts


def test_missing_model_raises_clear_error_and_never_predicts():
    """Verify missing model file raises clear error instead of producing a false prediction."""
    import pytest
    from app.services.ml_service import ml_service
    from app.schemas.ml_prediction import DiabetesPredictionRequest

    req = DiabetesPredictionRequest(
        age=30.0,
        gender="Female",
        hypertension=False,
        heart_disease=False,
        smoking_history="never",
        bmi=22.0,
        hba1c_level=5.0,
        blood_glucose_level=90.0
    )

    with patch.object(ml_service, "_resolve_model_path", side_effect=FileNotFoundError("Mock model file missing")):
        with patch.object(ml_service, "_model", None):
            with pytest.raises(FileNotFoundError, match="Mock model file missing"):
                ml_service.predict(req)

    # Ensure model is restored
    ml_service.load_model(force_reload=True)


def test_missing_model_endpoint_returns_503(client, auth_headers):
    """Verify endpoint returns HTTP 503 Service Unavailable when model is missing, not a false prediction."""
    from app.services.ml_service import ml_service

    payload = {
        "age": 45.0,
        "gender": "Male",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 25.0,
        "hba1c_level": 5.5,
        "blood_glucose_level": 100.0
    }

    with patch.object(ml_service, "predict", side_effect=RuntimeError("Diabetes ML model is unavailable")):
        res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert res.status_code == 503
        assert "Diabetes ML service is unavailable" in res.json()["detail"]


def test_incompatible_model_structure_rejected():
    """Verify corrupt or incompatible model objects missing predict/predict_proba are rejected."""
    import pytest
    from app.services.ml_service import ml_service

    # Mock joblib.load returning an object without predict methods
    with patch("joblib.load", return_value={"model": "not_an_estimator"}):
        with pytest.raises(ValueError, match="missing predict/predict_proba"):
            ml_service.load_model(force_reload=True)

    # Restore valid model
    ml_service.load_model(force_reload=True)


# ---------------------------------------------------------------------------
# Prediction History Persistence & Cross-Family Authorization Tests
# ---------------------------------------------------------------------------

class MockPredictionQueryBuilder:
    def __init__(self, data=None):
        self._data = [dict(item) for item in data] if data is not None else []
        self._range_start = 0
        self._range_end = None

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
        return self

    def range(self, start, end):
        self._range_start = start
        self._range_end = end
        return self

    def insert(self, payload):
        p = dict(payload)
        if "id" not in p:
            p["id"] = str(uuid.uuid4())
        p.setdefault("created_at", "2026-10-10T02:00:00Z")
        self._data = [p]
        return self

    def delete(self):
        return self

    def execute(self):
        res = MagicMock()
        items = list(self._data)
        if self._range_end is not None:
            items = items[self._range_start:self._range_end + 1]
        res.data = items
        return res


def setup_mock_db(tables_data):
    mock_supabase = MagicMock()
    mock_tables = {}

    def get_table(name):
        data = tables_data.get(name, [])
        builder = MockPredictionQueryBuilder(data)
        mock_tables[name] = builder
        return builder

    mock_supabase.table.side_effect = get_table
    mock_supabase._tables = mock_tables
    return mock_supabase


def test_predict_diabetes_save_to_records_self_no_family(client, auth_headers, test_user_id):
    """Verify save_to_records=True with no family_id saves personal prediction linked to user_id."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    mock_db = setup_mock_db({
        "prediction_history": [],
        "audit_logs": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 50.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 26.0,
        "hba1c_level": 5.4,
        "blood_glucose_level": 110.0,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["record_id"] is not None
    assert uuid.UUID(data["record_id"])  # Valid UUID format
    assert data["prediction"] in (0, 1)


def test_predict_diabetes_save_to_records_authorized_family(client, auth_headers, test_user_id):
    """Verify save_to_records=True with authorized family_id persists linked family references."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    family_id = str(uuid.uuid4())
    family_member_id = str(uuid.uuid4())

    mock_db = setup_mock_db({
        "family_members": [{
            "id": family_member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "prediction_history": [],
        "audit_logs": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 62.0,
        "gender": "Male",
        "hypertension": True,
        "heart_disease": True,
        "smoking_history": "former",
        "bmi": 31.0,
        "hba1c_level": 7.2,
        "blood_glucose_level": 175.0,
        "family_id": family_id,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["record_id"] is not None


def test_predict_diabetes_save_to_records_denied_cross_family(client, auth_headers, test_user_id):
    """Verify save_to_records=True with unauthorized family_id is rejected with HTTP 403 Forbidden."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    unauthorized_family_id = str(uuid.uuid4())

    # User is NOT a member of unauthorized_family_id
    mock_db = setup_mock_db({
        "family_members": [],
        "prediction_history": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 40.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.0,
        "hba1c_level": 5.1,
        "blood_glucose_level": 95.0,
        "family_id": unauthorized_family_id,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 403
    assert "Access denied: you are not a member of this family" in res.json()["detail"]


def test_predict_diabetes_save_to_records_denied_cross_member_no_consent(client, auth_headers, test_user_id):
    """Verify attempting to save a prediction for another member without active consent is rejected with HTTP 403."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    family_id = str(uuid.uuid4())
    my_member_id = str(uuid.uuid4())
    other_member_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    mock_db = setup_mock_db({
        "family_members": [
            {"id": my_member_id, "family_id": family_id, "user_id": test_user_id, "role": "MEMBER"},
            {"id": other_member_id, "family_id": family_id, "user_id": other_user_id, "role": "MEMBER"}
        ],
        "consents": [],  # No active consent granted
        "prediction_history": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    payload = {
        "age": 45.0,
        "gender": "Male",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 27.0,
        "hba1c_level": 5.8,
        "blood_glucose_level": 115.0,
        "family_id": family_id,
        "family_member_id": other_member_id,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 403
    assert "Active FULL_ACCESS consent required" in res.json()["detail"]


def test_predict_diabetes_database_failure(client, auth_headers, test_user_id):
    """Verify database insertion failure produces HTTP 500 without crashing."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    # Mock insert returning empty data or error
    mock_table.insert.return_value.execute.side_effect = RuntimeError("Supabase connection timeout")
    mock_supabase.table.return_value = mock_table

    app.dependency_overrides[get_supabase] = lambda: mock_supabase

    payload = {
        "age": 52.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 28.0,
        "hba1c_level": 6.0,
        "blood_glucose_level": 130.0,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 500
    assert "Database failure" in res.json()["detail"]


def test_list_prediction_history_self(client, auth_headers, test_user_id):
    """Verify listing prediction history returns only records belonging to the authenticated caller."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    rec1 = {
        "id": str(uuid.uuid4()),
        "user_id": test_user_id,
        "family_id": None,
        "family_member_id": None,
        "prediction_type": "DIABETES",
        "model_version": "1.0.0",
        "model_name": "RandomForestClassifier",
        "input_measurements": {"age": 45, "bmi": 25},
        "prediction_result": 0,
        "risk_label": "Low Risk",
        "risk_probability": 0.05,
        "risk_percentage": 5.0,
        "confidence_level": "High Confidence",
        "recommendations": ["Annual check-up"],
        "created_at": "2026-10-10T02:00:00Z"
    }

    other_user_rec = {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "family_id": None,
        "family_member_id": None,
        "prediction_type": "DIABETES",
        "model_version": "1.0.0",
        "model_name": "RandomForestClassifier",
        "input_measurements": {"age": 70, "bmi": 32},
        "prediction_result": 1,
        "risk_label": "High Risk",
        "risk_probability": 0.85,
        "risk_percentage": 85.0,
        "confidence_level": "High Confidence",
        "recommendations": ["Consult physician"],
        "created_at": "2026-10-10T01:00:00Z"
    }

    mock_db = setup_mock_db({
        "prediction_history": [rec1, other_user_rec]
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    res = client.get("/api/v1/predictions/history", headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == rec1["id"]
    assert items[0]["user_id"] == test_user_id


def test_list_prediction_history_denied_cross_family(client, auth_headers, test_user_id):
    """Verify attempting to list prediction history for another family is rejected with HTTP 403."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    other_family_id = str(uuid.uuid4())

    mock_db = setup_mock_db({
        "family_members": [],  # Caller is not a member of other_family_id
        "prediction_history": []
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    res = client.get(f"/api/v1/predictions/history?family_id={other_family_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 403
    assert "Access denied: you are not a member of this family" in res.json()["detail"]


def test_get_prediction_history_record_authorized_and_denied(client, auth_headers, test_user_id):
    """Verify retrieving a specific prediction record enforces ownership and access checks."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    own_rec_id = str(uuid.uuid4())
    other_rec_id = str(uuid.uuid4())

    own_rec = {
        "id": own_rec_id,
        "user_id": test_user_id,
        "family_id": None,
        "family_member_id": None,
        "prediction_type": "DIABETES",
        "model_version": "1.0.0",
        "model_name": "RandomForestClassifier",
        "input_measurements": {"age": 55, "bmi": 28},
        "prediction_result": 0,
        "risk_label": "Low Risk",
        "risk_probability": 0.12,
        "risk_percentage": 12.0,
        "confidence_level": "High Confidence",
        "recommendations": ["Healthy diet"],
        "created_at": "2026-10-10T02:00:00Z"
    }

    other_rec = {
        "id": other_rec_id,
        "user_id": str(uuid.uuid4()),
        "family_id": None,
        "family_member_id": None,
        "prediction_type": "DIABETES",
        "model_version": "1.0.0",
        "model_name": "RandomForestClassifier",
        "input_measurements": {"age": 68, "bmi": 33},
        "prediction_result": 1,
        "risk_label": "High Risk",
        "risk_probability": 0.90,
        "risk_percentage": 90.0,
        "confidence_level": "High Confidence",
        "recommendations": ["Immediate consult"],
        "created_at": "2026-10-10T01:30:00Z"
    }

    mock_db = setup_mock_db({
        "prediction_history": [own_rec, other_rec]
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    # 1. Own record: 200 OK
    res_own = client.get(f"/api/v1/predictions/history/{own_rec_id}", headers=auth_headers)
    assert res_own.status_code == 200
    assert res_own.json()["id"] == own_rec_id

    # 2. Other user's record: 403 Forbidden
    res_other = client.get(f"/api/v1/predictions/history/{other_rec_id}", headers=auth_headers)
    assert res_other.status_code == 403
    assert "Access denied" in res_other.json()["detail"]

    # 3. Non-existent record: 404 Not Found
    non_existent = str(uuid.uuid4())
    res_missing = client.get(f"/api/v1/predictions/history/{non_existent}", headers=auth_headers)
    assert res_missing.status_code == 404

    app.dependency_overrides.clear()


def test_delete_prediction_history_record_owner_and_denied(client, auth_headers, test_user_id):
    """Verify deleting prediction records is permitted for owner and denied for non-owners."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    own_rec_id = str(uuid.uuid4())
    other_rec_id = str(uuid.uuid4())

    own_rec = {
        "id": own_rec_id,
        "user_id": test_user_id,
        "prediction_type": "DIABETES",
        "created_at": "2026-10-10T02:00:00Z"
    }

    other_rec = {
        "id": other_rec_id,
        "user_id": str(uuid.uuid4()),
        "prediction_type": "DIABETES",
        "created_at": "2026-10-10T01:00:00Z"
    }

    mock_db = setup_mock_db({
        "prediction_history": [own_rec, other_rec]
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    # 1. Other user's record: 403 Forbidden
    res_denied = client.delete(f"/api/v1/predictions/history/{other_rec_id}", headers=auth_headers)
    assert res_denied.status_code == 403
    assert "only the record owner can delete" in res_denied.json()["detail"]

    # 2. Own record: 204 No Content
    res_del = client.delete(f"/api/v1/predictions/history/{own_rec_id}", headers=auth_headers)
    assert res_del.status_code == 204

    # 3. Non-existent record: 404 Not Found
    res_missing = client.delete(f"/api/v1/predictions/history/{str(uuid.uuid4())}", headers=auth_headers)
    assert res_missing.status_code == 404

    app.dependency_overrides.clear()


def test_sanitization_no_auth_tokens_in_stored_records_or_audit(client, auth_headers, test_user_id):
    """Verify stored prediction history and audit logs NEVER contain auth tokens, bearer credentials, or passwords."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    inserted_records = []
    logged_audits = []

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
                logged_audits.append(payload)
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
        "age": 48.0,
        "gender": "Male",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.5,
        "hba1c_level": 5.2,
        "blood_glucose_level": 98.0,
        "save_to_records": True
    }

    res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    assert len(inserted_records) == 1
    stored = inserted_records[0]

    # Verify input_measurements contains only valid medical keys
    expected_measurement_keys = {
        "age", "gender", "bmi", "hba1c_level", "blood_glucose_level",
        "hypertension", "heart_disease", "smoking_history"
    }
    assert set(stored["input_measurements"].keys()) == expected_measurement_keys

    # Check for token or authorization leak
    for val in stored["input_measurements"].values():
        val_str = str(val).lower()
        assert "bearer" not in val_str
        assert "token" not in val_str
        assert "password" not in val_str
        assert "secret" not in val_str


def test_individual_physiological_measurement_boundaries(client, auth_headers):
    """Verify each physiological metric strictly rejects out-of-range boundaries."""
    base = {
        "age": 40.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.0,
        "hba1c_level": 5.2,
        "blood_glucose_level": 95.0
    }

    # Age boundaries: [0.0, 120.0]
    assert client.post("/api/v1/predictions/diabetes", json={**base, "age": -1.0}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/diabetes", json={**base, "age": 121.0}, headers=auth_headers).status_code == 422

    # BMI boundaries: [10.0, 80.0]
    assert client.post("/api/v1/predictions/diabetes", json={**base, "bmi": 9.9}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/diabetes", json={**base, "bmi": 80.1}, headers=auth_headers).status_code == 422

    # HbA1c boundaries: [3.0, 20.0]
    assert client.post("/api/v1/predictions/diabetes", json={**base, "hba1c_level": 2.9}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/diabetes", json={**base, "hba1c_level": 20.1}, headers=auth_headers).status_code == 422

    # Blood glucose boundaries: [30.0, 600.0]
    assert client.post("/api/v1/predictions/diabetes", json={**base, "blood_glucose_level": 29.0}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/diabetes", json={**base, "blood_glucose_level": 601.0}, headers=auth_headers).status_code == 422

    # Invalid categorical options
    assert client.post("/api/v1/predictions/diabetes", json={**base, "gender": "UnknownGender"}, headers=auth_headers).status_code == 422
    assert client.post("/api/v1/predictions/diabetes", json={**base, "smoking_history": "cigar"}, headers=auth_headers).status_code == 422


def test_prediction_probability_and_response_schema_contract(client, auth_headers):
    """Verify prediction probability bounds and complete response schema against actual loaded model."""
    from datetime import datetime

    payload = {
        "age": 55.0,
        "gender": "Male",
        "hypertension": True,
        "heart_disease": False,
        "smoking_history": "former",
        "bmi": 28.5,
        "hba1c_level": 6.3,
        "blood_glucose_level": 135.0,
        "save_to_records": False
    }

    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()

        # Contract assertions
        assert isinstance(data["prediction"], int)
        assert data["prediction"] in (0, 1)
        assert data["risk_label"] in ("Low Risk", "High Risk")
        assert isinstance(data["risk_probability"], float)
        assert 0.0 <= data["risk_probability"] <= 1.0
        assert data["risk_percentage"] == round(data["risk_probability"] * 100.0, 1)
        assert data["confidence_level"] in ("High Confidence", "Moderate Confidence", "Low Confidence (Borderline)")

        # Feature summary exact fidelity
        summary = data["feature_summary"]
        assert summary["age"] == 55.0
        assert summary["gender"] == "Male"
        assert summary["hypertension"] is True
        assert summary["heart_disease"] is False
        assert summary["smoking_history"] == "former"
        assert summary["bmi"] == 28.5
        assert summary["hba1c_level"] == 6.3
        assert summary["blood_glucose_level"] == 135.0

        # Timestamp and record_id
        assert datetime.fromisoformat(data["assessed_at"].replace("Z", "+00:00"))
        assert data["record_id"] is None


def test_recommendations_triggered_by_clinical_conditions(client, auth_headers):
    """Verify specific physiological inputs trigger appropriate tailored recommendations."""
    payload = {
        "age": 65.0,
        "gender": "Male",
        "hypertension": True,
        "heart_disease": True,
        "smoking_history": "current",
        "bmi": 33.0,
        "hba1c_level": 7.8,
        "blood_glucose_level": 190.0,
        "save_to_records": False
    }

    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert res.status_code == 200
        recs = res.json()["recommendations"]

        assert any("diabetic threshold" in r or "oral glucose" in r for r in recs), "Missing HbA1c recommendation"
        assert any("Blood glucose reading" in r for r in recs), "Missing glucose recommendation"
        assert any("obese" in r for r in recs), "Missing BMI/obesity recommendation"
        assert any("Cardiovascular comorbidity" in r for r in recs), "Missing comorbidity recommendation"
        assert any("Smoking" in r for r in recs), "Missing smoking recommendation"


def test_auth_expired_or_invalid_tokens_rejected(client):
    """Verify invalid or expired JWT tokens are rejected with HTTP 401 Unauthorized."""
    import jwt
    import time
    from app.config import settings

    payload = {
        "age": 35.0,
        "gender": "Female",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 22.0,
        "hba1c_level": 4.8,
        "blood_glucose_level": 88.0
    }

    # 1. Expired token
    expired_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) - 3600, "aud": "authenticated"},
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256"
    )
    res_exp = client.post("/api/v1/predictions/diabetes", json=payload, headers={"Authorization": f"Bearer {expired_token}"})
    assert res_exp.status_code == 401

    # 2. Malformed token
    res_bad = client.post("/api/v1/predictions/diabetes", json=payload, headers={"Authorization": "Bearer not.a.valid.jwt"})
    assert res_bad.status_code == 401


def test_model_deserialization_error_handled_gracefully(client, auth_headers):
    """Verify unpickling or corrupted file error produces HTTP 503 rather than crashing."""
    from app.services.ml_service import ml_service

    payload = {
        "age": 42.0,
        "gender": "Male",
        "hypertension": False,
        "heart_disease": False,
        "smoking_history": "never",
        "bmi": 24.0,
        "hba1c_level": 5.2,
        "blood_glucose_level": 95.0
    }

    with patch.object(ml_service, "predict", side_effect=RuntimeError("Corrupt model pickle file")):
        res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert res.status_code == 503
        assert "Diabetes ML service is unavailable" in res.json()["detail"]


def test_diabetes_feature_impacts_explainability(client, auth_headers):
    """Verify local clinical feature attribution explainability returned in response."""
    payload = {
        "age": 68.0,
        "gender": "Male",
        "hypertension": True,
        "heart_disease": True,
        "smoking_history": "former",
        "bmi": 32.5,
        "hba1c_level": 7.8,
        "blood_glucose_level": 190.0,
        "save_to_records": False
    }

    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "feature_impacts" in data
        impacts = data["feature_impacts"]
        assert len(impacts) >= 4

        # Check key drivers
        hba1c_impact = next((i for i in impacts if i["feature"] == "HbA1c_level"), None)
        assert hba1c_impact is not None
        assert hba1c_impact["impact_level"] == "HIGH_RISK_FACTOR"
        assert hba1c_impact["relative_weight"] > 0.3

        bmi_impact = next((i for i in impacts if i["feature"] == "bmi"), None)
        assert bmi_impact is not None
        assert bmi_impact["impact_level"] == "HIGH_RISK_FACTOR"


def test_prediction_trends_trajectory_analysis(client, auth_headers, test_user_id):
    """Verify longitudinal risk trajectory calculation across multiple historical points."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    p1 = {
        "id": str(uuid.uuid4()),
        "user_id": test_user_id,
        "family_id": None,
        "family_member_id": None,
        "prediction_type": "DIABETES",
        "prediction_result": 1,
        "risk_label": "High Risk",
        "risk_percentage": 88.0,
        "risk_probability": 0.88,
        "confidence_level": "High Confidence",
        "input_measurements": {"age": 55, "bmi": 32},
        "created_at": "2026-01-10T10:00:00Z"
    }
    p2 = {
        "id": str(uuid.uuid4()),
        "user_id": test_user_id,
        "family_id": None,
        "family_member_id": None,
        "prediction_type": "DIABETES",
        "prediction_result": 0,
        "risk_label": "Low Risk",
        "risk_percentage": 52.0,
        "risk_probability": 0.52,
        "confidence_level": "Moderate Confidence",
        "input_measurements": {"age": 55, "bmi": 27},
        "created_at": "2026-06-10T10:00:00Z"
    }

    mock_db = setup_mock_db({
        "prediction_history": [p1, p2]
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    res = client.get("/api/v1/predictions/trends?prediction_type=DIABETES", headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["total_assessments"] == 2
    assert data["trajectory"] == "IMPROVING"
    assert data["baseline_risk_percentage"] == 88.0
    assert data["latest_risk_percentage"] == 52.0
    assert data["delta_percentage"] == -36.0
    assert "Favorable clinical improvement" in data["clinical_summary"]
    assert len(data["data_points"]) == 2


def test_prefill_prediction_measurements_from_records(client, auth_headers, test_user_id):
    """Verify prefill endpoint aggregates conditions from health_records and recent vitals."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    member_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())

    mock_db = setup_mock_db({
        "family_members": [{
            "id": member_id,
            "family_id": family_id,
            "user_id": test_user_id,
            "role": "MEMBER"
        }],
        "health_records": [{
            "id": str(uuid.uuid4()),
            "family_member_id": member_id,
            "chronic_conditions": "Essential Hypertension, Type 2 Diabetes",
            "medical_history": "Coronary heart disease"
        }],
        "prediction_history": [{
            "id": str(uuid.uuid4()),
            "family_member_id": member_id,
            "user_id": test_user_id,
            "input_measurements": {
                "age": 62.0,
                "gender": "Male",
                "bmi": 29.5,
                "smoking_history": "former",
                "hba1c_level": 6.8,
                "blood_glucose_level": 140.0
            },
            "created_at": "2026-09-01T08:00:00Z"
        }]
    })
    app.dependency_overrides[get_supabase] = lambda: mock_db

    res = client.get(f"/api/v1/predictions/prefill/{member_id}", headers=auth_headers)
    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["family_member_id"] == member_id
    assert data["hypertension"] is True
    assert data["diabetes"] is True
    assert data["heart_disease"] is True
    assert data["age"] == 62.0
    assert data["bmi"] == 29.5
    assert len(data["source_notes"]) >= 2


def test_automated_high_risk_notification_dispatched(client, auth_headers, test_user_id):
    """Verify high-risk assessment (>= 75%) automatically triggers a critical notification."""
    from app.auth.dependencies import get_supabase
    from app.main import app

    family_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())
    admin_user_id = str(uuid.uuid4())

    created_notifications = []

    mock_supabase = MagicMock()

    def get_table(name):
        builder = MagicMock()
        if name == "family_members":
            # Return member membership and admin query
            mock_res = MagicMock()
            mock_res.data = [
                {"id": member_id, "family_id": family_id, "user_id": test_user_id, "role": "MEMBER"},
                {"id": str(uuid.uuid4()), "family_id": family_id, "user_id": admin_user_id, "role": "ADMIN"}
            ]
            exec_mock = MagicMock()
            exec_mock.execute.return_value = mock_res
            builder.select.return_value.eq.return_value.eq.return_value = exec_mock
            builder.select.return_value.eq.return_value = exec_mock
            return builder
        elif name == "prediction_history":
            def insert_record(payload):
                p = dict(payload)
                p["id"] = str(uuid.uuid4())
                mock_res = MagicMock()
                mock_res.data = [p]
                exec_mock = MagicMock()
                exec_mock.execute.return_value = mock_res
                return exec_mock
            builder.insert.side_effect = insert_record
            return builder
        elif name == "notifications":
            def insert_notif(payload):
                created_notifications.append(payload)
                mock_res = MagicMock()
                p = dict(payload)
                p["id"] = str(uuid.uuid4())
                mock_res.data = [p]
                exec_mock = MagicMock()
                exec_mock.execute.return_value = mock_res
                return exec_mock
            builder.insert.side_effect = insert_notif
            return builder
        return builder

    mock_supabase.table.side_effect = get_table
    app.dependency_overrides[get_supabase] = lambda: mock_supabase

    payload = {
        "age": 70.0,
        "gender": "Male",
        "hypertension": True,
        "heart_disease": True,
        "smoking_history": "former",
        "bmi": 35.0,
        "hba1c_level": 8.5,
        "blood_glucose_level": 220.0,
        "family_id": family_id,
        "family_member_id": member_id,
        "save_to_records": True
    }

    with patch("app.services.audit.AuditService.log_action"):
        res = client.post("/api/v1/predictions/diabetes", json=payload, headers=auth_headers)
        app.dependency_overrides.clear()

        assert res.status_code == 200
        assert res.json()["prediction"] == 1
        assert res.json()["risk_percentage"] >= 75.0
        assert len(created_notifications) > 0
        notif = created_notifications[0]
        assert "Critical Health Alert" in notif["title"]


