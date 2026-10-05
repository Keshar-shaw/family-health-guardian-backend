from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.medicine import (
    MedicineCreate,
    MedicineUpdate,
    MedicineResponse,
)
from supabase import Client

router = APIRouter(prefix="/medicines", tags=["Medicines"])


def verify_medicine_access(
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
            "Active FULL_ACCESS consent required to modify medicines for this family member"
            if require_full_access
            else "Active consent required to access medicines for this family member"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=err_msg)

    return member


@router.post("", response_model=MedicineResponse, status_code=status.HTTP_201_CREATED)
def create_medicine(
    medicine_in: MedicineCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Register a new medicine for a family member.
    Caller must be the family member themselves or have ACTIVE FULL_ACCESS consent.
    """
    member = verify_medicine_access(
        supabase=supabase,
        family_member_id=medicine_in.family_member_id,
        user_id=current_user.sub,
        require_full_access=True
    )

    med_dict = medicine_in.model_dump()
    med_dict["family_member_id"] = str(medicine_in.family_member_id)
    if med_dict.get("start_date"):
        med_dict["start_date"] = str(med_dict["start_date"])
    if med_dict.get("end_date"):
        med_dict["end_date"] = str(med_dict["end_date"])

    res = supabase.table("medicines").insert(med_dict).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create medicine record")
    created = res.data[0]

    from app.services.audit import AuditService, AuditAction, AuditResourceType
    AuditService.log_action(
        supabase=supabase,
        actor_user_id=current_user.sub,
        action=AuditAction.MEDICINE_CREATED.value,
        resource_type=AuditResourceType.MEDICINE.value,
        resource_id=UUID(created["id"]),
        family_id=UUID(member["family_id"]) if member.get("family_id") else None,
        family_member_id=medicine_in.family_member_id,
        metadata={"medicine_name": created.get("medicine_name"), "dosage": created.get("dosage")}
    )
    return created


@router.get("", response_model=List[MedicineResponse])
def list_medicines(
    family_member_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    List medicines.
    If family_member_id is provided, filters for that specific member after access check.
    If omitted, returns all medicines the current user has authorized access to view.
    """
    if family_member_id is not None:
        verify_medicine_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        query = supabase.table("medicines").select("*").eq("family_member_id", str(family_member_id))
        if is_active is not None:
            query = query.eq("is_active", is_active)
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

    query = supabase.table("medicines").select("*").in_("family_member_id", authorized_member_ids)
    if is_active is not None:
        query = query.eq("is_active", is_active)
    records_res = query.execute()
    return records_res.data if records_res.data else []


@router.get("/{id}", response_model=MedicineResponse)
def get_medicine(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve details of a specific medicine by ID.
    Caller must be the owner or have active consent for the associated family member.
    """
    res = supabase.table("medicines").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine record not found")
    med = res.data[0]

    verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(med["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=False
    )
    return med


@router.put("/{id}", response_model=MedicineResponse)
def update_medicine(
    id: UUID,
    medicine_in: MedicineUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Update an existing medicine record.
    Caller must be the owner or have ACTIVE FULL_ACCESS consent for the associated family member.
    """
    res = supabase.table("medicines").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine record not found")
    med = res.data[0]

    member = verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(med["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    update_fields = medicine_in.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update")

    if "start_date" in update_fields and update_fields["start_date"]:
        update_fields["start_date"] = str(update_fields["start_date"])
    if "end_date" in update_fields and update_fields["end_date"]:
        update_fields["end_date"] = str(update_fields["end_date"])

    update_res = supabase.table("medicines").update(update_fields).eq("id", str(id)).execute()
    if not update_res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update medicine record")
    updated = update_res.data[0]

    from app.services.audit import AuditService, AuditAction, AuditResourceType
    AuditService.log_action(
        supabase=supabase,
        actor_user_id=current_user.sub,
        action=AuditAction.MEDICINE_UPDATED.value,
        resource_type=AuditResourceType.MEDICINE.value,
        resource_id=id,
        family_id=UUID(member["family_id"]) if member.get("family_id") else None,
        family_member_id=UUID(med["family_member_id"]),
        metadata={"updated_fields": list(update_fields.keys())}
    )
    return updated


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_medicine(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Delete a medicine record.
    Caller must be the owner or have ACTIVE FULL_ACCESS consent for the associated family member.
    """
    res = supabase.table("medicines").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine record not found")
    med = res.data[0]

    verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(med["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    supabase.table("medicines").delete().eq("id", str(id)).execute()
    return None
