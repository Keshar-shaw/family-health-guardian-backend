from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List, Optional
from uuid import UUID
import logging

from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.ml_prediction import (
    DiabetesPredictionRequest,
    DiabetesPredictionResponse,
    HypertensionPredictionRequest,
    HypertensionPredictionResponse,
    PredictionHistoryResponse
)
from app.services.ml_service import ml_service, EXPECTED_FEATURES
from app.services.hypertension_service import hypertension_ml_service, EXPECTED_HYPERTENSION_FEATURES
from app.services.audit import AuditService
from app.schemas.audit_log import AuditAction, AuditResourceType
from app.api.health_records import verify_member_access
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
    When save_to_records is True, validates family authorization and persists the prediction
    to prediction_history with an immutable audit trail.
    """
    try:
        result = ml_service.predict(req)
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

    # If persistence is requested, enforce authorization and save to prediction_history
    if req.save_to_records:
        family_id_str: Optional[str] = None
        target_member_id_str: Optional[str] = None

        if req.family_id:
            try:
                family_uuid = UUID(req.family_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid family_id format")

            # Verify caller is an active member of this family
            fm_check = supabase.table("family_members") \
                .select("*") \
                .eq("family_id", str(family_uuid)) \
                .eq("user_id", current_user.sub) \
                .execute()

            if not fm_check.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: you are not a member of this family"
                )

            family_id_str = str(family_uuid)
            caller_member_id = fm_check.data[0]["id"]

            if req.family_member_id:
                try:
                    member_uuid = UUID(req.family_member_id)
                except ValueError:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid family_member_id format")

                # Verify target member exists in the same family and caller has write access
                target_member = verify_member_access(
                    supabase=supabase,
                    family_member_id=member_uuid,
                    user_id=current_user.sub,
                    require_full_access=True
                )
                if str(target_member.get("family_id")) != family_id_str:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Provided family_member_id does not belong to the specified family"
                    )
                target_member_id_str = str(member_uuid)
            else:
                target_member_id_str = str(caller_member_id)

        elif req.family_member_id:
            # family_member_id specified without family_id
            try:
                member_uuid = UUID(req.family_member_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid family_member_id format")

            target_member = verify_member_access(
                supabase=supabase,
                family_member_id=member_uuid,
                user_id=current_user.sub,
                require_full_access=True
            )
            target_member_id_str = str(member_uuid)
            family_id_str = str(target_member.get("family_id")) if target_member.get("family_id") else None

        # Build sanitized record payload (NEVER stores tokens or auth credentials)
        record_payload = {
            "user_id": current_user.sub,
            "family_id": family_id_str,
            "family_member_id": target_member_id_str,
            "prediction_type": "DIABETES",
            "model_version": "1.0.0",
            "model_name": "RandomForestClassifier",
            "input_measurements": {
                "age": req.age,
                "gender": req.gender.value,
                "bmi": req.bmi,
                "hba1c_level": req.hba1c_level,
                "blood_glucose_level": req.blood_glucose_level,
                "hypertension": req.hypertension,
                "heart_disease": req.heart_disease,
                "smoking_history": req.smoking_history.value
            },
            "prediction_result": result.prediction,
            "risk_label": result.risk_label,
            "risk_probability": result.risk_probability,
            "risk_percentage": result.risk_percentage,
            "confidence_level": result.confidence_level,
            "recommendations": result.recommendations
        }

        try:
            insert_res = supabase.table("prediction_history").insert(record_payload).execute()
            if not insert_res.data:
                raise RuntimeError("Empty response received from prediction_history insert")
            saved_record = insert_res.data[0]
            result.record_id = str(saved_record["id"])
        except Exception as db_err:
            logger.error("Failed to persist prediction history: %s", str(db_err), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database failure: could not save prediction history: {str(db_err)}"
            )

        # Audit log the persistent creation
        AuditService.log_action(
            supabase=supabase,
            actor_user_id=current_user.sub,
            action=AuditAction.HEALTH_RECORD_CREATED.value,
            resource_type=AuditResourceType.HEALTH_RECORD.value,
            resource_id=UUID(result.record_id) if result.record_id else None,
            family_id=UUID(family_id_str) if family_id_str else None,
            family_member_id=UUID(target_member_id_str) if target_member_id_str else None,
            metadata={
                "action_type": "ML_PREDICTION_SAVED",
                "prediction_type": "DIABETES",
                "risk_label": result.risk_label,
                "risk_percentage": result.risk_percentage,
                "confidence_level": result.confidence_level
            }
        )
    else:
        # Audit log pure inference without saving measurements to history
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


@router.get("/hypertension/metadata", response_model=Dict[str, Any])
def get_hypertension_model_metadata():
    """Retrieve metadata, feature list, and clinical metric descriptions for the Hypertension ML model."""
    expected_features = hypertension_ml_service.get_expected_features()
    return {
        "model_name": "RandomForestClassifier",
        "disease_target": "Hypertension Risk",
        "model_version": "1.0.0",
        "features_count": len(expected_features),
        "expected_features": expected_features,
        "feature_details": {
            "age": {"type": "float", "range": "0 - 120", "description": "Patient age in years (primary epidemiological risk factor)"},
            "gender": {"type": "string", "options": ["Male", "Female", "Other"]},
            "heart_disease": {"type": "boolean", "description": "Existing cardiovascular comorbidity"},
            "smoking_history": {"type": "string", "options": ["never", "current", "former", "ever", "not current", "No Info"]},
            "bmi": {"type": "float", "normal_range": "18.5 - 24.9", "description": "Body Mass Index (kg/m2)"},
            "hba1c_level": {"type": "float", "normal_range": "< 5.7%", "prediabetes": "5.7 - 6.4%", "diabetes": ">= 6.5%"},
            "blood_glucose_level": {"type": "float", "normal_fasting": "70 - 99 mg/dL", "diabetes": ">= 126 mg/dL fasting"},
            "diabetes": {"type": "boolean", "description": "Diagnosed diabetes comorbidity"}
        },
        "regulatory_disclaimer": (
            "This model provides statistical risk stratification based on demographic, lifestyle, "
            "and metabolic factors. It does NOT predict continuous systolic/diastolic blood pressure (mmHg), "
            "is NOT an FDA-cleared diagnostic device, and does NOT replace sphygmomanometer measurement."
        )
    }


@router.post("/hypertension", response_model=HypertensionPredictionResponse)
def predict_hypertension_risk(
    req: HypertensionPredictionRequest,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Execute ML inference to predict patient hypertension risk and probability.
    When save_to_records is True, validates family authorization and persists the prediction
    to prediction_history with an immutable audit trail.
    """
    try:
        result = hypertension_ml_service.predict(req)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        logger.error("Hypertension ML service unavailable: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Hypertension ML service is unavailable: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error during hypertension prediction inference: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference execution failed: {str(e)}"
        )

    # If persistence is requested, enforce authorization and save to prediction_history
    if req.save_to_records:
        family_id_str: Optional[str] = None
        target_member_id_str: Optional[str] = None

        if req.family_id:
            try:
                family_uuid = UUID(req.family_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid family_id format")

            # Verify caller is an active member of this family
            fm_check = supabase.table("family_members") \
                .select("*") \
                .eq("family_id", str(family_uuid)) \
                .eq("user_id", current_user.sub) \
                .execute()

            if not fm_check.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: you are not a member of this family"
                )

            family_id_str = str(family_uuid)
            caller_member_id = fm_check.data[0]["id"]

        if req.family_member_id:
            try:
                member_uuid = UUID(req.family_member_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid family_member_id format")

            # Verify caller has full-access consent for target family member
            target_member = verify_member_access(
                supabase=supabase,
                family_member_id=member_uuid,
                user_id=current_user.sub,
                require_full_access=True
            )
            target_member_id_str = str(member_uuid)
            family_id_str = str(target_member.get("family_id")) if target_member.get("family_id") else None

        # Build sanitized record payload (NEVER stores tokens or auth credentials)
        record_payload = {
            "user_id": current_user.sub,
            "family_id": family_id_str,
            "family_member_id": target_member_id_str,
            "prediction_type": "HYPERTENSION",
            "model_version": "1.0.0",
            "model_name": "RandomForestClassifier",
            "input_measurements": {
                "age": req.age,
                "gender": req.gender.value,
                "bmi": req.bmi,
                "hba1c_level": req.hba1c_level,
                "blood_glucose_level": req.blood_glucose_level,
                "heart_disease": req.heart_disease,
                "diabetes": req.diabetes,
                "smoking_history": req.smoking_history.value
            },
            "prediction_result": result.prediction,
            "risk_label": result.risk_label,
            "risk_probability": result.risk_probability,
            "risk_percentage": result.risk_percentage,
            "confidence_level": result.confidence_level,
            "recommendations": result.recommendations
        }

        try:
            insert_res = supabase.table("prediction_history").insert(record_payload).execute()
            if not insert_res.data:
                raise RuntimeError("Empty response received from prediction_history insert")
            saved_record = insert_res.data[0]
            result.record_id = str(saved_record["id"])
        except Exception as db_err:
            logger.error("Failed to persist prediction history: %s", str(db_err), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database failure: could not save prediction history: {str(db_err)}"
            )

        # Audit log the persistent creation
        AuditService.log_action(
            supabase=supabase,
            actor_user_id=current_user.sub,
            action=AuditAction.HEALTH_RECORD_CREATED.value,
            resource_type=AuditResourceType.HEALTH_RECORD.value,
            resource_id=UUID(result.record_id) if result.record_id else None,
            family_id=UUID(family_id_str) if family_id_str else None,
            family_member_id=UUID(target_member_id_str) if target_member_id_str else None,
            metadata={
                "action_type": "ML_PREDICTION_SAVED",
                "prediction_type": "HYPERTENSION",
                "risk_label": result.risk_label,
                "risk_percentage": result.risk_percentage,
                "confidence_level": result.confidence_level
            }
        )
    else:
        # Audit log pure inference without saving measurements to history
        AuditService.log_action(
            supabase=supabase,
            actor_user_id=current_user.sub,
            action=AuditAction.HEALTH_RECORD_CREATED.value,
            resource_type=AuditResourceType.HEALTH_RECORD.value,
            resource_id=None,
            metadata={
                "action_type": "ML_INFERENCE_HYPERTENSION",
                "risk_label": result.risk_label,
                "risk_percentage": result.risk_percentage,
                "confidence_level": result.confidence_level
            }
        )

    return result


@router.get("/history", response_model=List[PredictionHistoryResponse])
def list_prediction_history(
    family_id: Optional[UUID] = None,
    family_member_id: Optional[UUID] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    List prediction history records with strict cross-family authorization.
    If family_id is provided, verifies caller is a member of that family.
    """
    if family_id is not None:
        fm_check = supabase.table("family_members") \
            .select("id") \
            .eq("family_id", str(family_id)) \
            .eq("user_id", current_user.sub) \
            .execute()
        if not fm_check.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you are not a member of this family"
            )

        query = supabase.table("prediction_history").select("*").eq("family_id", str(family_id))
        if family_member_id is not None:
            verify_member_access(
                supabase=supabase,
                family_member_id=family_member_id,
                user_id=current_user.sub,
                require_full_access=False
            )
            query = query.eq("family_member_id", str(family_member_id))
    elif family_member_id is not None:
        verify_member_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        query = supabase.table("prediction_history").select("*").eq("family_member_id", str(family_member_id))
    else:
        # Default: user's own predictions
        query = supabase.table("prediction_history").select("*").eq("user_id", current_user.sub)

    res = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return res.data if res.data else []


@router.get("/history/{record_id}", response_model=PredictionHistoryResponse)
def get_prediction_history_record(
    record_id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve a specific prediction history record by ID.
    Enforces authorization: caller must be the record owner or have active consent for the associated member.
    """
    res = supabase.table("prediction_history").select("*").eq("id", str(record_id)).execute()
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction history record not found"
        )
    record = res.data[0]

    # Self-access
    if record.get("user_id") == current_user.sub:
        return record

    # Target family member consent access
    if record.get("family_member_id"):
        verify_member_access(
            supabase=supabase,
            family_member_id=UUID(record["family_member_id"]),
            user_id=current_user.sub,
            require_full_access=False
        )
        return record

    # Family member access
    if record.get("family_id"):
        fm_check = supabase.table("family_members") \
            .select("id") \
            .eq("family_id", str(record["family_id"])) \
            .eq("user_id", current_user.sub) \
            .execute()
        if fm_check.data:
            return record

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: you do not have permission to view this prediction record"
    )


@router.delete("/history/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prediction_history_record(
    record_id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Delete a prediction history record.
    Only the record creator/owner can delete their prediction record.
    """
    res = supabase.table("prediction_history").select("*").eq("id", str(record_id)).execute()
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction history record not found"
        )
    record = res.data[0]

    if record.get("user_id") != current_user.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: only the record owner can delete this prediction record"
        )

    supabase.table("prediction_history").delete().eq("id", str(record_id)).execute()
    return None

