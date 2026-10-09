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
            self.load_model()
        except Exception as e:
            logger.warning("Diabetes ML model could not be pre-loaded on init: %s", e)

    @classmethod
    def get_instance(cls) -> "DiabetesMLService":
        if cls._instance is None:
            cls._instance = DiabetesMLService()
        return cls._instance

    @property
    def is_loaded(self) -> bool:
        """Return True if model is loaded in memory and ready for inference."""
        return self._model is not None

    def _resolve_model_path(self) -> Path:
        """
        Deterministically resolve the model file path relative to the backend project root.
        Never relies on current working directory (CWD) or user-supplied input.
        """
        env_path = os.getenv("DIABETES_MODEL_PATH")
        if env_path:
            p = Path(env_path).resolve()
            if p.is_file():
                return p
            raise FileNotFoundError(f"Configured DIABETES_MODEL_PATH not found: {p}")

        # Deterministic project path: backend/app/services/ml_service.py -> backend/models/diabetes_model.pkl
        project_root = Path(__file__).resolve().parent.parent.parent
        project_model_path = project_root / "models" / "diabetes_model.pkl"

        if project_model_path.is_file():
            return project_model_path

        raise FileNotFoundError(
            f"Diabetes ML model file not found at project location: {project_model_path}"
        )

    def load_model(self, force_reload: bool = False) -> None:
        """
        Load the model into memory and cache it.
        Avoids reloading from disk on every request.
        """
        if self._model is not None and not force_reload:
            return

        model_path = self._resolve_model_path()
        logger.info("Loading Diabetes ML model from project path %s", model_path)
        try:
            loaded_obj = joblib.load(model_path)
        except Exception as e:
            self._model = None
            logger.error("Failed to deserialize diabetes ML model from %s: %s", model_path, e)
            raise RuntimeError(f"Failed to deserialize diabetes ML model file: {e}") from e

        if isinstance(loaded_obj, dict) and 'model' in loaded_obj:
            estimator = loaded_obj['model']
        else:
            estimator = loaded_obj

        if not hasattr(estimator, "predict") or not hasattr(estimator, "predict_proba"):
            self._model = None
            raise ValueError(
                f"Incompatible model object loaded from {model_path}: missing predict/predict_proba methods"
            )

        self._model = estimator
        logger.info("Diabetes ML model loaded and cached successfully.")

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

    # Backward compatibility alias
    _load_model = load_model

    def predict(self, req: DiabetesPredictionRequest) -> DiabetesPredictionResponse:
        if self._model is None:
            self.load_model()
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
