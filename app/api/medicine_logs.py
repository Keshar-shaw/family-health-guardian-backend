from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from datetime import datetime, timezone
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.api.medicines import verify_medicine_access
from app.schemas.medicine_log import (
    MedicineLogCreate,
    MedicineLogStatusUpdate,
    MedicineLogResponse,
    MedicineLogStatus,
)
from supabase import Client

router = APIRouter(prefix="/medicine-logs", tags=["Medicine Logs"])


@router.post("", response_model=MedicineLogResponse, status_code=status.HTTP_201_CREATED)
def create_medicine_log(
    log_in: MedicineLogCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Log an intake event for a medicine (TAKEN, MISSED, or SKIPPED).
    Requires caller to be the family member or have ACTIVE FULL_ACCESS consent.
    """
    # Fetch parent medicine
    med_res = supabase.table("medicines").select("*").eq("id", str(log_in.medicine_id)).execute()
    if not med_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine not found")
    med = med_res.data[0]

    family_member_id = UUID(med["family_member_id"])

    # Security check: never trust client-supplied family_member_id without verifying match
    if log_in.family_member_id is not None and str(log_in.family_member_id) != str(family_member_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Supplied family_member_id does not match the medicine's family member"
        )

    verify_medicine_access(
        supabase=supabase,
        family_member_id=family_member_id,
        user_id=current_user.sub,
        require_full_access=True
    )

    # Optional schedule validation
    if log_in.schedule_id is not None:
        sched_res = supabase.table("medicine_schedules").select("*").eq("id", str(log_in.schedule_id)).execute()
        if not sched_res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine schedule not found")
        if sched_res.data[0].get("medicine_id") != str(log_in.medicine_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Schedule does not belong to the specified medicine"
            )

    log_dict = {
        "medicine_id": str(log_in.medicine_id),
        "family_member_id": str(family_member_id),
        "status": log_in.status.value,
        "notes": log_in.notes,
    }

    if log_in.schedule_id:
        log_dict["schedule_id"] = str(log_in.schedule_id)
    if log_in.scheduled_at:
        log_dict["scheduled_at"] = log_in.scheduled_at.isoformat()

    # If marked as TAKEN and taken_at is not provided, record current timestamp
    if log_in.status == MedicineLogStatus.TAKEN:
        log_dict["taken_at"] = (
            log_in.taken_at.isoformat()
            if log_in.taken_at
            else datetime.now(timezone.utc).isoformat()
        )
    elif log_in.taken_at:
        log_dict["taken_at"] = log_in.taken_at.isoformat()

    res = supabase.table("medicine_logs").insert(log_dict).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create medicine log")
    return res.data[0]


@router.get("", response_model=List[MedicineLogResponse])
def list_medicine_logs(
    medicine_id: Optional[UUID] = None,
    family_member_id: Optional[UUID] = None,
    log_status: Optional[MedicineLogStatus] = None,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    List medicine logs.
    Can be filtered by medicine_id, family_member_id, or log_status.
    If no filter is provided, returns logs for all members the user is authorized to view.
    """
    if medicine_id is not None:
        med_res = supabase.table("medicines").select("*").eq("id", str(medicine_id)).execute()
        if not med_res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine not found")
        med = med_res.data[0]
        verify_medicine_access(
            supabase=supabase,
            family_member_id=UUID(med["family_member_id"]),
            user_id=current_user.sub,
            require_full_access=False
        )
        query = supabase.table("medicine_logs").select("*").eq("medicine_id", str(medicine_id))
        if log_status is not None:
            query = query.eq("status", log_status.value)
        res = query.execute()
        return res.data if res.data else []

    if family_member_id is not None:
        verify_medicine_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        query = supabase.table("medicine_logs").select("*").eq("family_member_id", str(family_member_id))
        if log_status is not None:
            query = query.eq("status", log_status.value)
        res = query.execute()
        return res.data if res.data else []

    # Get all self family_member IDs
    self_members = supabase.table("family_members").select("id").eq("user_id", current_user.sub).execute()
    authorized_member_ids = [m["id"] for m in (self_members.data or [])]

    # Get active consents granted to current_user
    consents_res = supabase.table("consents").select("granter_id, family_id") \
        .eq("grantee_id", current_user.sub) \
        .eq("status", "ACTIVE") \
        .execute()

    if consents_res.data:
        for c in consents_res.data:
            cm_res = supabase.table("family_members").select("id") \
                .eq("family_id", c["family_id"]) \
                .eq("user_id", c["granter_id"]) \
                .execute()
            if cm_res.data:
                authorized_member_ids.extend([m["id"] for m in cm_res.data])

    if not authorized_member_ids:
        return []

    query = supabase.table("medicine_logs").select("*").in_("family_member_id", authorized_member_ids)
    if log_status is not None:
        query = query.eq("status", log_status.value)
    res = query.execute()
    return res.data if res.data else []


@router.get("/{id}", response_model=MedicineLogResponse)
def get_medicine_log(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve details of a specific medicine log by ID.
    Caller must have authorized access to view the family member's records.
    """
    res = supabase.table("medicine_logs").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine log not found")
    log_rec = res.data[0]

    verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(log_rec["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=False
    )
    return log_rec


@router.patch("/{id}/status", response_model=MedicineLogResponse)
def update_medicine_log_status(
    id: UUID,
    status_update: MedicineLogStatusUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Mark medicine log status as TAKEN, MISSED, or SKIPPED.
    Caller must have ACTIVE FULL_ACCESS consent for the associated family member.
    """
    res = supabase.table("medicine_logs").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine log not found")
    log_rec = res.data[0]

    verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(log_rec["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    update_dict = {"status": status_update.status.value}

    if status_update.notes is not None:
        update_dict["notes"] = status_update.notes

    if status_update.taken_at:
        update_dict["taken_at"] = status_update.taken_at.isoformat()
    elif status_update.status == MedicineLogStatus.TAKEN and not log_rec.get("taken_at"):
        update_dict["taken_at"] = datetime.now(timezone.utc).isoformat()
    elif status_update.status in (MedicineLogStatus.MISSED, MedicineLogStatus.SKIPPED) and status_update.taken_at is None:
        update_dict["taken_at"] = None

    update_res = supabase.table("medicine_logs").update(update_dict).eq("id", str(id)).execute()
    if not update_res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update medicine log status")
    return update_res.data[0]
