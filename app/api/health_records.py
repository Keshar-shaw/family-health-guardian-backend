from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.health_record import (
    HealthRecordCreate,
    HealthRecordUpdate,
    HealthRecordResponse,
)
from supabase import Client

router = APIRouter(prefix="/health-records", tags=["Health Records"])


def verify_member_access(
    supabase: Client,
    family_member_id: UUID,
    user_id: str,
    require_full_access: bool = False
) -> dict:
    """
    Validates family member existence and verifies that the requesting user is either:
    1. The member themselves (self)
    2. A guardian/member with an ACTIVE consent (READ_ONLY or FULL_ACCESS for read; FULL_ACCESS for write)
    """
    member_res = supabase.table("family_members").select("*").eq("id", str(family_member_id)).execute()
    if not member_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Family member not found"
        )
    member = member_res.data[0]

    # Self-access is always authorized
    if member["user_id"] == user_id:
        return member

    # Non-self: check active consent
    query = supabase.table("consents").select("*") \
        .eq("granter_id", member["user_id"]) \
        .eq("grantee_id", user_id) \
        .eq("family_id", member["family_id"]) \
        .eq("status", "ACTIVE")

    if require_full_access:
        query = query.eq("permission_level", "FULL_ACCESS")
    
    consent_res = query.execute()
    if not consent_res.data:
        err_msg = (
            "Active FULL_ACCESS consent required to modify this health record"
            if require_full_access
            else "Active consent required to access this health record"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=err_msg)

    return member


@router.post("", response_model=HealthRecordResponse, status_code=status.HTTP_201_CREATED)
def create_health_record(
    record_in: HealthRecordCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Create a new health record for a family member.
    Caller must be the family member themselves or have ACTIVE FULL_ACCESS consent.
    """
    verify_member_access(
        supabase=supabase,
        family_member_id=record_in.family_member_id,
        user_id=current_user.sub,
        require_full_access=True
    )

    record_dict = record_in.model_dump()
    record_dict["family_member_id"] = str(record_in.family_member_id)

    res = supabase.table("health_records").insert(record_dict).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create health record")
    return res.data[0]


@router.get("", response_model=List[HealthRecordResponse])
def list_health_records(
    family_member_id: Optional[UUID] = None,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    List health records.
    If family_member_id is provided, checks permissions for that specific member.
    If not provided, returns records for all members the user is authorized to view (self + active consents).
    """
    if family_member_id is not None:
        verify_member_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        res = supabase.table("health_records").select("*").eq("family_member_id", str(family_member_id)).execute()
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

    records_res = supabase.table("health_records").select("*").in_("family_member_id", authorized_member_ids).execute()
    return records_res.data if records_res.data else []


@router.get("/{id}", response_model=HealthRecordResponse)
def get_health_record(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve a specific health record by ID.
    Caller must be the owner or have active consent for the associated family member.
    """
    res = supabase.table("health_records").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Health record not found")
    record = res.data[0]

    verify_member_access(
        supabase=supabase,
        family_member_id=UUID(record["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=False
    )
    return record


@router.put("/{id}", response_model=HealthRecordResponse)
def update_health_record(
    id: UUID,
    record_in: HealthRecordUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Update an existing health record.
    Caller must be the owner or have ACTIVE FULL_ACCESS consent for the associated family member.
    """
    res = supabase.table("health_records").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Health record not found")
    record = res.data[0]

    verify_member_access(
        supabase=supabase,
        family_member_id=UUID(record["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    update_fields = record_in.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update")

    update_res = supabase.table("health_records").update(update_fields).eq("id", str(id)).execute()
    if not update_res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update health record")
    return update_res.data[0]


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_health_record(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Delete a health record.
    Caller must be the owner or have ACTIVE FULL_ACCESS consent for the associated family member.
    """
    res = supabase.table("health_records").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Health record not found")
    record = res.data[0]

    verify_member_access(
        supabase=supabase,
        family_member_id=UUID(record["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    supabase.table("health_records").delete().eq("id", str(id)).execute()
    return None
