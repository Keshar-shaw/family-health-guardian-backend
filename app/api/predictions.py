from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any
import logging

from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.ml_prediction import (
    DiabetesPredictionRequest,
    DiabetesPredictionResponse
)
from app.services.ml_service import ml_service, EXPECTED_FEATURES
from app.services.audit import AuditService
from app.schemas.audit_log import AuditAction, AuditResourceType
from supabase import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predictions", tags=["ML Predictions"])


@router.get("/diabetes/metadata", response_model=Dict[str, Any])
def get_diabetes_model_metadata():
    """Retrieve metadata, feature list, and expected ranges for the Diabetes ML model."""
    expected_features = ml_service.get_expected_features()
    return {
        "model_name": "RandomForestClassifier",
        "disease_target": "Type 2 Diabetes Mellitus",
        "features_count": len(expected_features),
        "expected_features": expected_features,
        "feature_details": {
            "age": {"type": "float", "range": "0 - 120", "description": "Patient age in years"},
            "gender": {"type": "string", "options": ["Male", "Female", "Other"]},
            "hypertension": {"type": "boolean", "description": "High blood pressure diagnosis"},
            "heart_disease": {"type": "boolean", "description": "Heart disease diagnosis"},
            "smoking_history": {"type": "string", "options": ["never", "current", "former", "ever", "not current", "No Info"]},
            "bmi": {"type": "float", "normal_range": "18.5 - 24.9", "description": "Body Mass Index"},
            "hba1c_level": {"type": "float", "normal_range": "< 5.7%", "prediabetes": "5.7 - 6.4%", "diabetes": ">= 6.5%"},
            "blood_glucose_level": {"type": "float", "normal_fasting": "70 - 99 mg/dL", "diabetes": ">= 126 mg/dL fasting"}
        }
    }


@router.post("/diabetes", response_model=DiabetesPredictionResponse)
def predict_diabetes_risk(
    req: DiabetesPredictionRequest,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Execute ML inference to predict patient diabetes risk and probability.
    Optionally saves the risk assessment to health records and logs audit trail.
    """
    try:
        result = ml_service.predict(req)

        # Audit log the inference action
        AuditService.log_action(
            supabase=supabase,
            actor_user_id=current_user.sub,
            action=AuditAction.HEALTH_RECORD_CREATED.value,
            resource_type=AuditResourceType.HEALTH_RECORD.value,
            resource_id=None,
            metadata={
                "action_type": "ML_INFERENCE_DIABETES",
                "risk_label": result.risk_label,
                "risk_percentage": result.risk_percentage,
                "confidence_level": result.confidence_level
            }
        )

        return result
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        logger.error("Diabetes ML service unavailable: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Diabetes ML service is unavailable: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error during diabetes prediction inference: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference execution failed: {str(e)}"
        )
