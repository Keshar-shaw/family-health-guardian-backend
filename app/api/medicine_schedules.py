from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.api.medicines import verify_medicine_access
from app.schemas.medicine_schedule import (
    MedicineScheduleCreate,
    MedicineScheduleUpdate,
    MedicineScheduleResponse,
)
from supabase import Client

router = APIRouter(prefix="/medicine-schedules", tags=["Medicine Schedules"])


def get_medicine_and_verify_access(
    supabase: Client,
    medicine_id: UUID,
    user_id: str,
    require_full_access: bool = False
) -> dict:
    """Fetches parent medicine and verifies that current user has authorized access."""
    med_res = supabase.table("medicines").select("*").eq("id", str(medicine_id)).execute()
    if not med_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine not found")
    medicine = med_res.data[0]

    verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(medicine["family_member_id"]),
        user_id=user_id,
        require_full_access=require_full_access
    )
    return medicine


@router.post("", response_model=MedicineScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_medicine_schedule(
    schedule_in: MedicineScheduleCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Create a new intake schedule for a medicine.
    Requires caller to be the family member or have ACTIVE FULL_ACCESS consent.
    """
    get_medicine_and_verify_access(
        supabase=supabase,
        medicine_id=schedule_in.medicine_id,
        user_id=current_user.sub,
        require_full_access=True
    )

    sched_dict = schedule_in.model_dump()
    sched_dict["medicine_id"] = str(schedule_in.medicine_id)
    if sched_dict.get("start_date"):
        sched_dict["start_date"] = str(sched_dict["start_date"])
    if sched_dict.get("end_date"):
        sched_dict["end_date"] = str(sched_dict["end_date"])

    res = supabase.table("medicine_schedules").insert(sched_dict).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create medicine schedule")
    return res.data[0]


@router.get("", response_model=List[MedicineScheduleResponse])
def list_medicine_schedules(
    medicine_id: Optional[UUID] = None,
    family_member_id: Optional[UUID] = None,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    List medicine schedules.
    Can be filtered by specific medicine_id or family_member_id.
    If no filter is provided, returns schedules for all medicines the user is authorized to view.
    """
    if medicine_id is not None:
        get_medicine_and_verify_access(
            supabase=supabase,
            medicine_id=medicine_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        res = supabase.table("medicine_schedules").select("*").eq("medicine_id", str(medicine_id)).execute()
        return res.data if res.data else []

    if family_member_id is not None:
        verify_medicine_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        meds = supabase.table("medicines").select("id").eq("family_member_id", str(family_member_id)).execute()
        med_ids = [m["id"] for m in (meds.data or [])]
        if not med_ids:
            return []
        res = supabase.table("medicine_schedules").select("*").in_("medicine_id", med_ids).execute()
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

    meds = supabase.table("medicines").select("id").in_("family_member_id", authorized_member_ids).execute()
    med_ids = [m["id"] for m in (meds.data or [])]
    if not med_ids:
        return []

    res = supabase.table("medicine_schedules").select("*").in_("medicine_id", med_ids).execute()
    return res.data if res.data else []


@router.get("/{id}", response_model=MedicineScheduleResponse)
def get_medicine_schedule(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve details of a specific medicine schedule by ID.
    Caller must have authorized access to the parent medicine.
    """
    res = supabase.table("medicine_schedules").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine schedule not found")
    sched = res.data[0]

    get_medicine_and_verify_access(
        supabase=supabase,
        medicine_id=UUID(sched["medicine_id"]),
        user_id=current_user.sub,
        require_full_access=False
    )
    return sched


@router.put("/{id}", response_model=MedicineScheduleResponse)
def update_medicine_schedule(
    id: UUID,
    schedule_in: MedicineScheduleUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Update an existing medicine schedule.
    Caller must have ACTIVE FULL_ACCESS consent for the parent medicine.
    """
    res = supabase.table("medicine_schedules").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine schedule not found")
    sched = res.data[0]

    get_medicine_and_verify_access(
        supabase=supabase,
        medicine_id=UUID(sched["medicine_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    update_fields = schedule_in.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update")

    if "start_date" in update_fields and update_fields["start_date"]:
        update_fields["start_date"] = str(update_fields["start_date"])
    if "end_date" in update_fields and update_fields["end_date"]:
        update_fields["end_date"] = str(update_fields["end_date"])

    update_res = supabase.table("medicine_schedules").update(update_fields).eq("id", str(id)).execute()
    if not update_res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update medicine schedule")
    return update_res.data[0]


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_medicine_schedule(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Delete a medicine schedule.
    Caller must have ACTIVE FULL_ACCESS consent for the parent medicine.
    """
    res = supabase.table("medicine_schedules").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine schedule not found")
    sched = res.data[0]

    get_medicine_and_verify_access(
        supabase=supabase,
        medicine_id=UUID(sched["medicine_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    supabase.table("medicine_schedules").delete().eq("id", str(id)).execute()
    return None
