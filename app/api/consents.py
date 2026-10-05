from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.consent import (
    ConsentCreate,
    ConsentUpdate,
    ConsentResponse,
    ConsentStatus,
    ConsentPermission,
)
from supabase import Client

router = APIRouter(prefix="/consents", tags=["Consents & Access Permissions"])


@router.post("", response_model=ConsentResponse, status_code=status.HTTP_201_CREATED)
def grant_or_request_consent(
    consent_in: ConsentCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Create a consent access request.
    Current user is granter (granting access to grantee) or grantee (requesting access from granter).
    Both users must belong to the specified family.
    """
    if current_user.sub == str(consent_in.grantee_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot grant or request consent to oneself"
        )

    # Verify caller is a member of the target family
    caller_member = supabase.table("family_members").select("id") \
        .eq("family_id", str(consent_in.family_id)) \
        .eq("user_id", current_user.sub) \
        .execute()
    if not caller_member.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Caller is not a member of the specified family"
        )

    # Verify grantee is also a member of the target family
    grantee_member = supabase.table("family_members").select("id") \
        .eq("family_id", str(consent_in.family_id)) \
        .eq("user_id", str(consent_in.grantee_id)) \
        .execute()
    if not grantee_member.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Grantee is not a member of the specified family"
        )

    consent_data = consent_in.model_dump()
    consent_data["granter_id"] = current_user.sub
    consent_data["grantee_id"] = str(consent_in.grantee_id)
    consent_data["family_id"] = str(consent_in.family_id)
    consent_data["permission_level"] = consent_in.permission_level.value
    consent_data["status"] = ConsentStatus.PENDING.value

    res = supabase.table("consents").insert(consent_data).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create consent record")
    return res.data[0]


@router.get("", response_model=List[ConsentResponse])
def list_consents(
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """List all consent requests where current user is granter or grantee."""
    res = supabase.table("consents") \
        .select("*") \
        .or_(f"granter_id.eq.{current_user.sub},grantee_id.eq.{current_user.sub}") \
        .execute()
    
    return res.data if res.data else []


@router.patch("/{consent_id}", response_model=ConsentResponse)
def update_consent(
    consent_id: UUID,
    consent_up: ConsentUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Accept, revoke, or update consent permissions.
    Only the granter (data owner) can approve (ACTIVE) or elevate permissions (FULL_ACCESS).
    """
    existing = supabase.table("consents").select("*").eq("id", str(consent_id)).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Consent record not found")
    
    record = existing.data[0]
    is_granter = current_user.sub == record["granter_id"]
    is_grantee = current_user.sub == record["grantee_id"]

    if not is_granter and not is_grantee:
        raise HTTPException(status_code=403, detail="Not authorized to update this consent record")

    update_fields = consent_up.model_dump(exclude_unset=True)

    # Security check: only granter can approve consent (ACTIVE) or elevate permission
    if "status" in update_fields:
        target_status = update_fields["status"]
        if target_status == ConsentStatus.ACTIVE and not is_granter:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the patient (granter) can approve and activate consent"
            )
        update_fields["status"] = target_status.value

    if "permission_level" in update_fields and update_fields["permission_level"]:
        if not is_granter:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the patient (granter) can change consent permission levels"
            )
        update_fields["permission_level"] = update_fields["permission_level"].value

    res = supabase.table("consents").update(update_fields).eq("id", str(consent_id)).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to update consent record")
    return res.data[0]
