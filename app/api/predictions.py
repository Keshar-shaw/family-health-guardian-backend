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
    PredictionHistoryResponse,
    PredictionTrendsResponse,
    TrendDataPoint,
    PrefillPredictionResponse
)
from app.services.ml_service import ml_service, EXPECTED_FEATURES
from app.services.hypertension_service import hypertension_ml_service, EXPECTED_HYPERTENSION_FEATURES
from app.services.audit import AuditService
from app.schemas.audit_log import AuditAction, AuditResourceType
from app.services.notifications import NotificationService
from app.schemas.notification import NotificationType
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

        # Automated Alert Notification on Critical Risk (>= 75%)
        if result.prediction == 1 and result.risk_percentage >= 75.0 and target_member_id_str:
            try:
                recipient_user_ids = {current_user.sub}
                if family_id_str:
                    fm_admins = supabase.table("family_members").select("user_id").eq("family_id", family_id_str).eq("role", "ADMIN").execute()
                    if fm_admins.data:
                        recipient_user_ids.update(a["user_id"] for a in fm_admins.data)
                for uid in recipient_user_ids:
                    NotificationService.create_notification(
                        supabase=supabase,
                        user_id=uid,
                        family_member_id=target_member_id_str,
                        notification_type=NotificationType.EMERGENCY_SOS,
                        title=f"Critical Health Alert: {result.risk_label} Diabetes Risk ({result.risk_percentage}%)",
                        message=f"High risk detected ({result.risk_percentage}%) in diabetes assessment. Timely clinical consultation recommended.",
                        dispatch_immediately=True
                    )
            except Exception as notif_err:
                logger.warning("Could not create high risk alert notification: %s", notif_err)
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

        # Automated Alert Notification on Critical Risk (>= 70%)
        if result.prediction == 1 and result.risk_percentage >= 70.0 and target_member_id_str:
            try:
                recipient_user_ids = {current_user.sub}
                if family_id_str:
                    fm_admins = supabase.table("family_members").select("user_id").eq("family_id", family_id_str).eq("role", "ADMIN").execute()
                    if fm_admins.data:
                        recipient_user_ids.update(a["user_id"] for a in fm_admins.data)
                for uid in recipient_user_ids:
                    NotificationService.create_notification(
                        supabase=supabase,
                        user_id=uid,
                        family_member_id=target_member_id_str,
                        notification_type=NotificationType.EMERGENCY_SOS,
                        title=f"Critical Health Alert: {result.risk_label} Hypertension Risk ({result.risk_percentage}%)",
                        message=f"High risk detected ({result.risk_percentage}%) in hypertension assessment. Timely clinical consultation recommended.",
                        dispatch_immediately=True
                    )
            except Exception as notif_err:
                logger.warning("Could not create high risk alert notification: %s", notif_err)
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


@router.get("/trends", response_model=PredictionTrendsResponse)
def get_prediction_trends(
    family_member_id: Optional[UUID] = None,
    family_id: Optional[UUID] = None,
    prediction_type: str = "DIABETES",
    limit: int = 30,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Compute longitudinal risk trajectory analytics and clinical trend summaries across historical assessments.
    Enforces family and member authorization.
    """
    if family_id:
        fm_check = supabase.table("family_members") \
            .select("*") \
            .eq("family_id", str(family_id)) \
            .eq("user_id", current_user.sub) \
            .execute()
        if not fm_check.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you are not a member of this family"
            )

    if family_member_id:
        verify_member_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )

    # Query chronological history
    query = supabase.table("prediction_history") \
        .select("*") \
        .eq("prediction_type", prediction_type.upper())

    if family_member_id:
        query = query.eq("family_member_id", str(family_member_id))
    elif family_id:
        query = query.eq("family_id", str(family_id))
    else:
        query = query.eq("user_id", current_user.sub)

    res = query.order("created_at", desc=False).range(0, limit - 1).execute()
    records = res.data or []

    data_points: List[TrendDataPoint] = []
    for r in records:
        data_points.append(TrendDataPoint(
            record_id=str(r["id"]),
            assessed_at=r["created_at"],
            prediction_type=r["prediction_type"],
            risk_label=r["risk_label"],
            risk_percentage=float(r["risk_percentage"]),
            risk_probability=float(r["risk_probability"]),
            confidence_level=r.get("confidence_level", "Moderate Confidence"),
            key_metrics=r.get("input_measurements", {})
        ))

    total = len(data_points)
    if total < 2:
        trajectory = "INSUFFICIENT_DATA"
        latest = data_points[0].risk_percentage if total == 1 else None
        baseline = latest
        delta = 0.0 if total == 1 else None
        avg_risk = latest
        summary = (
            f"1 historical assessment found ({latest:.1f}% risk). "
            "At least 2 longitudinal assessments are required to calculate a trajectory trend."
            if total == 1 else
            "No historical assessments recorded yet for this profile."
        )
    else:
        baseline = data_points[0].risk_percentage
        latest = data_points[-1].risk_percentage
        delta = round(latest - baseline, 1)
        avg_risk = round(sum(d.risk_percentage for d in data_points) / total, 1)

        if delta <= -5.0:
            trajectory = "IMPROVING"
            summary = (
                f"Favorable clinical improvement: statistical risk has decreased by {abs(delta):.1f}% "
                f"(from {baseline:.1f}% baseline down to {latest:.1f}%). "
                "Current preventive lifestyle modifications are yielding positive health benefits."
            )
        elif delta >= 5.0:
            trajectory = "WORSENING"
            summary = (
                f"Elevating risk trajectory: statistical risk has increased by +{delta:.1f}% "
                f"(from {baseline:.1f}% baseline up to {latest:.1f}%). "
                "Coordinated clinical review and diagnostic laboratory tests are recommended."
            )
        else:
            trajectory = "STABLE"
            summary = (
                f"Stable health trajectory: risk remains consistent around {avg_risk:.1f}% "
                f"(latest: {latest:.1f}%, baseline: {baseline:.1f}%, delta: {delta:+.1f}%). "
                "Continue standard periodic preventive tracking."
            )

    return PredictionTrendsResponse(
        total_assessments=total,
        prediction_type=prediction_type.upper(),
        trajectory=trajectory,
        latest_risk_percentage=latest,
        baseline_risk_percentage=baseline,
        delta_percentage=delta,
        average_risk_percentage=avg_risk,
        clinical_summary=summary,
        data_points=data_points
    )


@router.get("/prefill/{family_member_id}", response_model=PrefillPredictionResponse)
def prefill_prediction_measurements(
    family_member_id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Intelligently pre-populate health metrics for a family member by aggregating known
    health records, chronic conditions, and recent assessment history.
    Enforces read access authorization.
    """
    member = verify_member_access(
        supabase=supabase,
        family_member_id=family_member_id,
        user_id=current_user.sub,
        require_full_access=False
    )

    notes: List[str] = []
    prefill = {
        "family_member_id": str(family_member_id),
        "age": None,
        "gender": None,
        "bmi": None,
        "hypertension": None,
        "heart_disease": None,
        "diabetes": None,
        "smoking_history": None,
        "hba1c_level": None,
        "blood_glucose_level": None,
        "source_notes": notes
    }

    # 1. Inspect existing health_records
    hr_res = supabase.table("health_records") \
        .select("*") \
        .eq("family_member_id", str(family_member_id)) \
        .execute()

    if hr_res.data:
        hr = hr_res.data[0]
        conditions = f"{hr.get('chronic_conditions') or ''} {hr.get('medical_history') or ''} {hr.get('current_conditions') or ''}".lower()
        
        if any(w in conditions for w in ["hypertension", "high blood pressure", "htn"]):
            prefill["hypertension"] = True
            notes.append("Hypertension diagnosed in chronic conditions record.")
            
        if any(w in conditions for w in ["heart disease", "coronary", "cardiac", "infarction"]):
            prefill["heart_disease"] = True
            notes.append("Cardiovascular pathology documented in medical history.")
            
        if any(w in conditions for w in ["diabetes", "diabetic", "t2d", "t1d"]):
            prefill["diabetes"] = True
            notes.append("Diabetes documented in chronic health record.")

    # 2. Inspect latest prediction_history for physical vitals
    ph_res = supabase.table("prediction_history") \
        .select("*") \
        .eq("family_member_id", str(family_member_id)) \
        .order("created_at", desc=True) \
        .range(0, 0) \
        .execute()

    if ph_res.data:
        last_measurements = ph_res.data[0].get("input_measurements", {})
        for k in ["age", "gender", "bmi", "smoking_history", "hba1c_level", "blood_glucose_level"]:
            if k in last_measurements and last_measurements[k] is not None:
                prefill[k] = last_measurements[k]
        created_str = ph_res.data[0].get("created_at", "")[:10]
        notes.append(f"Physical measurements auto-filled from recent assessment on {created_str}.")

    if not notes:
        notes.append("No previous health records or assessments found; blank profile initialized.")

    return PrefillPredictionResponse(**prefill)


