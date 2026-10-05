from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.api.medicines import verify_medicine_access
from app.schemas.emergency_contact import (
    EmergencyContactCreate,
    EmergencyContactUpdate,
    EmergencyContactResponse,
)
from supabase import Client

router = APIRouter(prefix="/emergency-contacts", tags=["Emergency Contacts"])


@router.post("", response_model=EmergencyContactResponse, status_code=status.HTTP_201_CREATED)
def create_emergency_contact(
    contact_in: EmergencyContactCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Register a new emergency contact for a family member.
    Caller must be the family member themselves or have ACTIVE FULL_ACCESS consent.
    """
    member = verify_medicine_access(
        supabase=supabase,
        family_member_id=contact_in.family_member_id,
        user_id=current_user.sub,
        require_full_access=True
    )

    contact_dict = contact_in.model_dump()
    contact_dict["family_member_id"] = str(contact_in.family_member_id)

    res = supabase.table("emergency_contacts").insert(contact_dict).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create emergency contact")
    created = res.data[0]

    from app.services.audit import AuditService, AuditAction, AuditResourceType
    AuditService.log_action(
        supabase=supabase,
        actor_user_id=current_user.sub,
        action=AuditAction.EMERGENCY_CONTACT_CHANGED.value,
        resource_type=AuditResourceType.EMERGENCY_CONTACT.value,
        resource_id=UUID(created["id"]),
        family_id=UUID(member["family_id"]) if member.get("family_id") else None,
        family_member_id=contact_in.family_member_id,
        metadata={"change": "CREATED", "name": created.get("name"), "priority": created.get("priority")}
    )
    return created


@router.get("", response_model=List[EmergencyContactResponse])
def list_emergency_contacts(
    family_member_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    List emergency contacts.
    If family_member_id is provided, checks access and lists contacts for that specific member.
    If omitted, lists contacts for all family members the current user has authorized access to.
    """
    if family_member_id is not None:
        verify_medicine_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        query = supabase.table("emergency_contacts").select("*").eq("family_member_id", str(family_member_id))
        if is_active is not None:
            query = query.eq("is_active", is_active)
        query = query.order("priority")
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

    query = supabase.table("emergency_contacts").select("*").in_("family_member_id", authorized_member_ids)
    if is_active is not None:
        query = query.eq("is_active", is_active)
    query = query.order("priority")
    res = query.execute()
    return res.data if res.data else []


@router.get("/{id}", response_model=EmergencyContactResponse)
def get_emergency_contact(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve details of a specific emergency contact by ID.
    Caller must have authorized access to the associated family member.
    """
    res = supabase.table("emergency_contacts").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency contact not found")
    contact = res.data[0]

    verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(contact["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=False
    )
    return contact


@router.put("/{id}", response_model=EmergencyContactResponse)
def update_emergency_contact(
    id: UUID,
    contact_in: EmergencyContactUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Update an emergency contact record.
    Caller must have ACTIVE FULL_ACCESS consent for the associated family member.
    """
    res = supabase.table("emergency_contacts").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency contact not found")
    contact = res.data[0]

    member = verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(contact["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    update_fields = contact_in.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update")

    update_res = supabase.table("emergency_contacts").update(update_fields).eq("id", str(id)).execute()
    if not update_res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update emergency contact")
    updated = update_res.data[0]

    from app.services.audit import AuditService, AuditAction, AuditResourceType
    AuditService.log_action(
        supabase=supabase,
        actor_user_id=current_user.sub,
        action=AuditAction.EMERGENCY_CONTACT_CHANGED.value,
        resource_type=AuditResourceType.EMERGENCY_CONTACT.value,
        resource_id=id,
        family_id=UUID(member["family_id"]) if member.get("family_id") else None,
        family_member_id=UUID(contact["family_member_id"]),
        metadata={"change": "UPDATED", "updated_fields": list(update_fields.keys())}
    )
    return updated


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_emergency_contact(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Delete an emergency contact record.
    Caller must have ACTIVE FULL_ACCESS consent for the associated family member.
    """
    res = supabase.table("emergency_contacts").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency contact not found")
    contact = res.data[0]

    member = verify_medicine_access(
        supabase=supabase,
        family_member_id=UUID(contact["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    supabase.table("emergency_contacts").delete().eq("id", str(id)).execute()

    from app.services.audit import AuditService, AuditAction, AuditResourceType
    AuditService.log_action(
        supabase=supabase,
        actor_user_id=current_user.sub,
        action=AuditAction.EMERGENCY_CONTACT_CHANGED.value,
        resource_type=AuditResourceType.EMERGENCY_CONTACT.value,
        resource_id=id,
        family_id=UUID(member["family_id"]) if member.get("family_id") else None,
        family_member_id=UUID(contact["family_member_id"]),
        metadata={"change": "DELETED", "name": contact.get("name")}
    )
    return None
