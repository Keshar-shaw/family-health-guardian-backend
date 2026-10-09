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

