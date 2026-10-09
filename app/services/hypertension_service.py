import os
from pathlib import Path
import logging
from typing import Optional, Tuple, List
import joblib
import numpy as np
import pandas as pd

from app.schemas.ml_prediction import (
    HypertensionPredictionRequest,
    HypertensionPredictionResponse,
    FeatureImpact,
    GenderEnum,
    SmokingHistoryEnum
)

logger = logging.getLogger(__name__)

# Expected model features in order derived from training workflow and saved model artifact
EXPECTED_HYPERTENSION_FEATURES = [
    'age',
    'heart_disease',
    'bmi',
    'HbA1c_level',
    'blood_glucose_level',
    'diabetes',
    'gender_Male',
    'gender_Other',
    'smoking_history_current',
    'smoking_history_ever',
    'smoking_history_former',
    'smoking_history_never',
    'smoking_history_not current'
]


class HypertensionMLService:
    _instance = None
    _model = None

    def __init__(self):
        try:
            self.load_model()
        except Exception as e:
            logger.warning("Hypertension ML model could not be pre-loaded on init: %s", e)

    @classmethod
    def get_instance(cls) -> "HypertensionMLService":
        if cls._instance is None:
            cls._instance = HypertensionMLService()
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
        env_path = os.getenv("HYPERTENSION_MODEL_PATH")
        if env_path:
            p = Path(env_path).resolve()
            if p.is_file():
                return p
            raise FileNotFoundError(f"Configured HYPERTENSION_MODEL_PATH not found: {p}")

        # Deterministic project path: backend/app/services/hypertension_service.py -> backend/models/hypertension_model.pkl
        project_root = Path(__file__).resolve().parent.parent.parent
        project_model_path = project_root / "models" / "hypertension_model.pkl"

        if project_model_path.is_file():
            return project_model_path

        raise FileNotFoundError(
            f"Hypertension ML model file not found at project location: {project_model_path}"
        )

    def load_model(self, force_reload: bool = False) -> None:
        """
        Load the model into memory and cache it.
        Avoids reloading from disk on every request.
        """
        if self._model is not None and not force_reload:
            return

        model_path = self._resolve_model_path()
        logger.info("Loading Hypertension ML model from project path %s", model_path)
        try:
            loaded_obj = joblib.load(model_path)
        except Exception as e:
            self._model = None
            logger.error("Failed to deserialize hypertension ML model from %s: %s", model_path, e)
            raise RuntimeError(f"Failed to deserialize hypertension ML model file: {e}") from e

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
        logger.info("Hypertension ML model loaded and cached successfully.")

    def get_expected_features(self) -> List[str]:
        """Derive expected feature names and ordering directly from the trained model."""
        if self._model is not None and hasattr(self._model, "feature_names_in_"):
            return list(self._model.feature_names_in_)
        return list(EXPECTED_HYPERTENSION_FEATURES)

    def build_feature_dataframe(self, req: HypertensionPredictionRequest) -> pd.DataFrame:
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
            'heart_disease': 1 if req.heart_disease else 0,
            'bmi': float(req.bmi),
            'HbA1c_level': float(req.hba1c_level),
            'blood_glucose_level': float(req.blood_glucose_level),
            'diabetes': 1 if req.diabetes else 0,
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

    def generate_recommendations(
        self,
        req: HypertensionPredictionRequest,
        prediction: int,
        prob_positive: float
    ) -> List[str]:
        recommendations = []

        if prediction == 1 or prob_positive >= 0.5:
            recommendations.append(
                "High statistical probability of hypertension detected. Schedule an in-person clinical blood pressure evaluation using an automated or manual sphygmomanometer."
            )
        elif prob_positive >= 0.25:
            recommendations.append(
                "Moderate hypertension risk detected. Maintain regular home blood pressure monitoring (AHA guideline: morning and evening measurements)."
            )
        else:
            recommendations.append(
                "Low statistical risk of hypertension detected. Continue standard annual preventive cardiovascular screenings."
            )

        if req.age >= 60.0:
            recommendations.append(
                f"At age {req.age:.0f}, isolated systolic hypertension risk increases due to natural arterial stiffening. Regular arterial pressure tracking is advised."
            )

        if req.bmi >= 30.0:
            recommendations.append(
                f"BMI of {req.bmi:.1f} indicates obesity, a major contributor to vascular resistance and hypertension. Adopting the DASH (Dietary Approaches to Stop Hypertension) diet and reducing dietary sodium (< 2,300 mg/day) is strongly advised."
            )
        elif req.bmi >= 25.0:
            recommendations.append(
                f"BMI of {req.bmi:.1f} classifies as overweight. Gradual weight reduction can reduce systolic blood pressure by approximately 1 mmHg per kg lost."
            )

        if req.heart_disease:
            recommendations.append(
                "Cardiovascular disease comorbidity present. Coordinated cardiovascular follow-up is critical to maintain target blood pressure (< 130/80 mmHg per ACC/AHA guidelines)."
            )

        if req.diabetes:
            recommendations.append(
                "Diabetes diagnosed. Strict blood pressure control (< 130/80 mmHg) is vital to delay or prevent diabetic nephropathy, retinopathy, and stroke."
            )

        if req.blood_glucose_level >= 140.0 or req.hba1c_level >= 6.5:
            recommendations.append(
                "Elevated glycemic indicators detected. Hyperglycemia promotes endothelial dysfunction and microvascular constriction; comprehensive metabolic monitoring is recommended."
            )

        if req.smoking_history in (SmokingHistoryEnum.current, SmokingHistoryEnum.ever):
            recommendations.append(
                "Smoking causes immediate sympathetic activation, heart rate elevation, and vascular endothelial damage. Smoking cessation substantially decreases long-term hypertension and stroke risks."
            )

        return recommendations

    def calculate_feature_impacts(
        self,
        req: HypertensionPredictionRequest,
        pred: int,
        prob_positive: float
    ) -> List[FeatureImpact]:
        """
        Calculate local clinical feature attribution explaining specific patient hypertension risk drivers.
        Weights reflect empirical Random Forest importance derived during model training.
        """
        impacts: List[FeatureImpact] = []

        # 1. Age (Weight ~ 0.537)
        if req.age >= 60.0:
            impacts.append(FeatureImpact(
                feature="age",
                display_name="Patient Age",
                value=req.age,
                impact_level="HIGH_RISK_FACTOR",
                relative_weight=0.537,
                description=f"Age {req.age:.0f} is the dominant contributor; vascular aging causes arterial wall thickening and arterial stiffness."
            ))
        elif req.age >= 45.0:
            impacts.append(FeatureImpact(
                feature="age",
                display_name="Patient Age",
                value=req.age,
                impact_level="MODERATE_RISK_FACTOR",
                relative_weight=0.537,
                description=f"Age {req.age:.0f} represents a moderate age-related hemodynamic risk tier."
            ))
        else:
            impacts.append(FeatureImpact(
                feature="age",
                display_name="Patient Age",
                value=req.age,
                impact_level="PROTECTIVE_FACTOR",
                relative_weight=0.537,
                description=f"Younger age ({req.age:.0f} years) serves as a favorable baseline protective cardiovascular factor."
            ))

        # 2. BMI (Weight ~ 0.190)
        if req.bmi >= 30.0:
            impacts.append(FeatureImpact(
                feature="bmi",
                display_name="Body Mass Index",
                value=req.bmi,
                impact_level="HIGH_RISK_FACTOR",
                relative_weight=0.190,
                description=f"BMI of {req.bmi:.1f} classifies as obese, significantly elevating systemic vascular resistance and cardiac output demand."
            ))
        elif req.bmi >= 25.0:
            impacts.append(FeatureImpact(
                feature="bmi",
                display_name="Body Mass Index",
                value=req.bmi,
                impact_level="MODERATE_RISK_FACTOR",
                relative_weight=0.190,
                description=f"BMI of {req.bmi:.1f} classifies as overweight, contributing to elevated resting arterial load."
            ))
        else:
            impacts.append(FeatureImpact(
                feature="bmi",
                display_name="Body Mass Index",
                value=req.bmi,
                impact_level="PROTECTIVE_FACTOR",
                relative_weight=0.190,
                description=f"BMI of {req.bmi:.1f} is within optimal normal bounds (18.5 - 24.9 kg/m2)."
            ))

        # 3. Diabetes Comorbidity (Weight ~ 0.081)
        if req.diabetes:
            impacts.append(FeatureImpact(
                feature="diabetes",
                display_name="Diabetes Comorbidity",
                value=True,
                impact_level="HIGH_RISK_FACTOR",
                relative_weight=0.081,
                description="Diabetes causes microvascular hardening and endothelial inflammation, strongly accelerating hypertension."
            ))

        # 4. Glycemic Markers (HbA1c ~ 0.058, Glucose ~ 0.051)
        if req.blood_glucose_level >= 140.0 or req.hba1c_level >= 6.5:
            impacts.append(FeatureImpact(
                feature="glycemic_markers",
                display_name="Elevated Glycemic Markers",
                value={"glucose": req.blood_glucose_level, "hba1c": req.hba1c_level},
                impact_level="MODERATE_RISK_FACTOR",
                relative_weight=0.109,
                description="Elevated circulating glucose increases arterial oxidative stress and renin-angiotensin-aldosterone system activity."
            ))

        # 5. Heart Disease (Weight ~ 0.031)
        if req.heart_disease:
            impacts.append(FeatureImpact(
                feature="heart_disease",
                display_name="Heart Disease Comorbidity",
                value=True,
                impact_level="HIGH_RISK_FACTOR",
                relative_weight=0.031,
                description="Existing cardiovascular pathology significantly reduces arterial compliance."
            ))

        # 6. Smoking (Weight ~ 0.052)
        if req.smoking_history in (SmokingHistoryEnum.current, SmokingHistoryEnum.ever, SmokingHistoryEnum.former):
            impacts.append(FeatureImpact(
                feature="smoking_history",
                display_name="Smoking History",
                value=req.smoking_history.value,
                impact_level="MODERATE_RISK_FACTOR",
                relative_weight=0.052,
                description="Active or past tobacco use accelerates arterial wall stiffness and sympathetic vasoconstriction."
            ))
        else:
            impacts.append(FeatureImpact(
                feature="smoking_history",
                display_name="Smoking History",
                value=req.smoking_history.value,
                impact_level="PROTECTIVE_FACTOR",
                relative_weight=0.052,
                description="Non-smoking status protects arterial compliance and endothelial function."
            ))

        return impacts

    def predict(self, req: HypertensionPredictionRequest) -> HypertensionPredictionResponse:
        if self._model is None:
            self.load_model()
        if self._model is None:
            raise RuntimeError("Hypertension ML model is not available")

        feature_df = self.build_feature_dataframe(req)

        pred = int(self._model.predict(feature_df)[0])
        prob_matrix = self._model.predict_proba(feature_df)
        prob_positive = float(prob_matrix[0][1])
        rounded_prob = round(prob_positive, 4)

        risk_label = "High Risk" if (pred == 1 or prob_positive >= 0.5) else "Low Risk"
        risk_pct = round(rounded_prob * 100.0, 1)

        # Confidence metric
        if prob_positive >= 0.8 or prob_positive <= 0.2:
            confidence = "High Confidence"
        elif prob_positive >= 0.65 or prob_positive <= 0.35:
            confidence = "Moderate Confidence"
        else:
            confidence = "Low Confidence (Borderline)"

        recommendations = self.generate_recommendations(req, pred, prob_positive)
        feature_impacts = self.calculate_feature_impacts(req, pred, prob_positive)

        return HypertensionPredictionResponse(
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
                "heart_disease": req.heart_disease,
                "diabetes": req.diabetes,
                "smoking_history": req.smoking_history.value
            },
            recommendations=recommendations,
            feature_impacts=feature_impacts
        )


hypertension_ml_service = HypertensionMLService.get_instance()
