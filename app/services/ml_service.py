import os
from pathlib import Path
import logging
from typing import Optional, Tuple, List
import joblib
import numpy as np
import pandas as pd

from app.schemas.ml_prediction import (
    DiabetesPredictionRequest,
    DiabetesPredictionResponse,
    GenderEnum,
    SmokingHistoryEnum
)

logger = logging.getLogger(__name__)

# Expected model features in order derived from training notebook and model artifact
EXPECTED_FEATURES = [
    'age',
    'hypertension',
    'heart_disease',
    'bmi',
    'HbA1c_level',
    'blood_glucose_level',
    'gender_Male',
    'gender_Other',
    'smoking_history_current',
    'smoking_history_ever',
    'smoking_history_former',
    'smoking_history_never',
    'smoking_history_not current'
]


class DiabetesMLService:
    _instance = None
    _model = None

    def __init__(self):
        try:
            self._load_model()
        except Exception as e:
            logger.warning("Diabetes ML model could not be pre-loaded at startup: %s", e)

    @classmethod
    def get_instance(cls) -> "DiabetesMLService":
        if cls._instance is None:
            cls._instance = DiabetesMLService()
        return cls._instance

    def _resolve_model_path(self) -> Path:
        base_dir = Path(__file__).resolve().parent.parent.parent
        primary_path = base_dir / "models" / "diabetes_model.pkl"
        if primary_path.exists():
            return primary_path

        cwd_path = Path.cwd() / "models" / "diabetes_model.pkl"
        if cwd_path.exists():
            return cwd_path

        raise FileNotFoundError(
            f"Diabetes ML model file not found. Looked in {primary_path} and {cwd_path}"
        )

    def _load_model(self):
        try:
            model_path = self._resolve_model_path()
            logger.info("Loading Diabetes ML model from %s", model_path)
            loaded_obj = joblib.load(model_path)
            if isinstance(loaded_obj, dict) and 'model' in loaded_obj:
                self._model = loaded_obj['model']
            else:
                self._model = loaded_obj
            logger.info("Diabetes ML model loaded successfully.")
        except Exception as e:
            logger.error("Error loading diabetes model: %s", e)
            raise

    def get_expected_features(self) -> List[str]:
        """Derive expected feature names and ordering directly from the trained model."""
        if self._model is not None and hasattr(self._model, "feature_names_in_"):
            return list(self._model.feature_names_in_)
        return list(EXPECTED_FEATURES)

    def build_feature_dataframe(self, req: DiabetesPredictionRequest) -> pd.DataFrame:
        """
        Construct a 1-row pandas DataFrame using the exact feature names and ordering
        expected by the trained RandomForestClassifier.
        Categorical dummy encoding matches the training get_dummies(drop_first=True) step.
        """
        features = self.get_expected_features()

        # Gender: 'Female' dropped as baseline in training drop_first=True
        gender_male = 1 if req.gender == GenderEnum.male else 0
        gender_other = 1 if req.gender == GenderEnum.other else 0

        # Smoking History: 'No Info' dropped as baseline in training drop_first=True
        smoking_current = 1 if req.smoking_history == SmokingHistoryEnum.current else 0
        smoking_ever = 1 if req.smoking_history == SmokingHistoryEnum.ever else 0
        smoking_former = 1 if req.smoking_history == SmokingHistoryEnum.former else 0
        smoking_never = 1 if req.smoking_history == SmokingHistoryEnum.never else 0
        smoking_not_current = 1 if req.smoking_history == SmokingHistoryEnum.not_current else 0

        data = {
            'age': float(req.age),
            'hypertension': 1 if req.hypertension else 0,
            'heart_disease': 1 if req.heart_disease else 0,
            'bmi': float(req.bmi),
            'HbA1c_level': float(req.hba1c_level),
            'blood_glucose_level': float(req.blood_glucose_level),
            'gender_Male': gender_male,
            'gender_Other': gender_other,
            'smoking_history_current': smoking_current,
            'smoking_history_ever': smoking_ever,
            'smoking_history_former': smoking_former,
            'smoking_history_never': smoking_never,
            'smoking_history_not current': smoking_not_current
        }

        df = pd.DataFrame([data], columns=features)
        return df

    def build_feature_vector(self, req: DiabetesPredictionRequest) -> np.ndarray:
        """Maintained for backward compatibility. Returns 2D float64 numpy array."""
        return self.build_feature_dataframe(req).to_numpy(dtype=np.float64)

    def generate_recommendations(
        self,
        req: DiabetesPredictionRequest,
        prediction: int,
        prob_positive: float
    ) -> List[str]:
        recommendations = []

        if prediction == 1 or prob_positive >= 0.5:
            recommendations.append("High probability of diabetes detected. Schedule a formal diagnostic oral glucose tolerance test with your healthcare provider.")
        elif prob_positive >= 0.25:
            recommendations.append("Moderate risk detected. Regular monitoring and preventive lifestyle modifications are strongly advised.")
        else:
            recommendations.append("Low risk of diabetes detected. Continue regular annual preventive health check-ups.")

        if req.hba1c_level >= 6.5:
            recommendations.append(f"HbA1c level of {req.hba1c_level}% is in the diabetic threshold (>= 6.5%). Medical evaluation is recommended.")
        elif req.hba1c_level >= 5.7:
            recommendations.append(f"HbA1c level of {req.hba1c_level}% indicates pre-diabetes range (5.7% - 6.4%). Dietary intervention is advised.")

        if req.blood_glucose_level >= 140.0:
            recommendations.append(f"Blood glucose reading of {req.blood_glucose_level} mg/dL is elevated. Maintain a regular fasting log.")

        if req.bmi >= 30.0:
            recommendations.append(f"BMI of {req.bmi:.1f} classifies as obese. A supervised nutritional and exercise plan can drastically improve metabolic sensitivity.")
        elif req.bmi >= 25.0:
            recommendations.append(f"BMI of {req.bmi:.1f} classifies as overweight. Maintaining a calorie-balanced diet is recommended.")

        if req.hypertension or req.heart_disease:
            recommendations.append("Cardiovascular comorbidity present. Coordinate care with your cardiologist/physician for dual lipid and glycemic control.")

        if req.smoking_history in (SmokingHistoryEnum.current, SmokingHistoryEnum.ever):
            recommendations.append("Smoking significantly increases microvascular complication risks. Smoking cessation counseling is strongly recommended.")

        return recommendations

    def predict(self, req: DiabetesPredictionRequest) -> DiabetesPredictionResponse:
        if self._model is None:
            self._load_model()
        if self._model is None:
            raise RuntimeError("Diabetes ML model is not available")

        feature_df = self.build_feature_dataframe(req)

        pred = int(self._model.predict(feature_df)[0])
        prob_matrix = self._model.predict_proba(feature_df)
        prob_positive = float(prob_matrix[0][1])

        risk_label = "High Risk" if (pred == 1 or prob_positive >= 0.5) else "Low Risk"
        risk_pct = round(prob_positive * 100.0, 1)

        # Confidence metric
        if prob_positive >= 0.8 or prob_positive <= 0.2:
            confidence = "High Confidence"
        elif prob_positive >= 0.65 or prob_positive <= 0.35:
            confidence = "Moderate Confidence"
        else:
            confidence = "Low Confidence (Borderline)"

        recommendations = self.generate_recommendations(req, pred, prob_positive)

        return DiabetesPredictionResponse(
            prediction=pred,
            risk_label=risk_label,
            risk_probability=round(prob_positive, 4),
            risk_percentage=risk_pct,
            confidence_level=confidence,
            feature_summary={
                "age": req.age,
                "gender": req.gender.value,
                "bmi": req.bmi,
                "hba1c_level": req.hba1c_level,
                "blood_glucose_level": req.blood_glucose_level,
                "hypertension": req.hypertension,
                "heart_disease": req.heart_disease,
                "smoking_history": req.smoking_history.value
            },
            recommendations=recommendations
        )


ml_service = DiabetesMLService.get_instance()
