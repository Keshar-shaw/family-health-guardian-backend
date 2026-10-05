from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException, status
from supabase import Client


def verify_family_member_access(
    supabase: Client,
    family_member_id: UUID,
    user_id: str,
    require_full_access: bool = False
) -> dict:
    """
    Validates family member existence and verifies that the requesting user is either:
    1. The member themselves (self-access)
    2. A guardian/member with an ACTIVE consent within the same family
       (READ_ONLY or FULL_ACCESS for read; FULL_ACCESS for write)
    
    Ensures that a client-supplied family_member_id is never trusted without authorization,
    and that users cannot access records across unrelated families.
    """
    member_res = supabase.table("family_members").select("*").eq("id", str(family_member_id)).execute()
    if not member_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Family member not found"
        )
    member = member_res.data[0]

    # 1. Self-access is always authorized
    if member["user_id"] == user_id:
        return member

    # 2. Non-self: check active consent within the same family
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
            "Active FULL_ACCESS consent required to modify healthcare data for this family member"
            if require_full_access
            else "Active consent required to access healthcare data for this family member"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=err_msg)

    return member


def get_authorized_family_member_ids(
    supabase: Client,
    user_id: str,
    family_id: Optional[UUID] = None
) -> List[str]:
    """
    Retrieves all family_member_ids that the user is authorized to access:
    1. The user's own family memberships (self)
    2. Other members who have granted ACTIVE consent to this user in shared families
    """
    query = supabase.table("family_members").select("id, family_id").eq("user_id", user_id)
    if family_id:
        query = query.eq("family_id", str(family_id))
    self_members = query.execute()

    authorized_member_ids = [m["id"] for m in (self_members.data or [])]
    user_family_ids = {m["family_id"] for m in (self_members.data or [])}

    # Fetch active consents where current user is the grantee
    consent_query = supabase.table("consents").select("granter_id, family_id") \
        .eq("grantee_id", user_id) \
        .eq("status", "ACTIVE")
    
    if family_id:
        consent_query = consent_query.eq("family_id", str(family_id))
    
    consents_res = consent_query.execute()

    if consents_res.data:
        for c in consents_res.data:
            # Grantee must be a member of that family, or consent must be in one of user's active families
            if not user_family_ids or c["family_id"] in user_family_ids:
                cm_res = supabase.table("family_members").select("id") \
                    .eq("family_id", c["family_id"]) \
                    .eq("user_id", c["granter_id"]) \
                    .execute()
                if cm_res.data:
                    authorized_member_ids.extend([m["id"] for m in cm_res.data])

    return list(dict.fromkeys(authorized_member_ids))


def verify_sos_member_access(
    supabase: Client,
    family_member_id: UUID,
    user_id: str,
    allow_triggerer: Optional[str] = None
) -> dict:
    """
    Validates family member existence and verifies the requesting user is either:
    1. The triggerer of the event (if allow_triggerer is provided and matches)
    2. The member themselves (self)
    3. A member of the same family
    """
    if allow_triggerer and allow_triggerer == user_id:
        # Caller is the triggerer of this specific event
        member_res = supabase.table("family_members").select("*").eq("id", str(family_member_id)).execute()
        if member_res.data:
            return member_res.data[0]

    member_res = supabase.table("family_members").select("*").eq("id", str(family_member_id)).execute()
    if not member_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Family member not found"
        )
    member = member_res.data[0]

    if member["user_id"] == user_id:
        return member

    # Check if user belongs to the same family
    membership_res = supabase.table("family_members").select("*") \
        .eq("family_id", member["family_id"]) \
        .eq("user_id", user_id) \
        .execute()
    
    if not membership_res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: caller is not in the same family as this member"
        )

    return member


def verify_family_membership(
    supabase: Client,
    family_id: UUID,
    user_id: str
) -> dict:
    """Validates that user is an active member of the given family."""
    membership = supabase.table("family_members").select("*") \
        .eq("family_id", str(family_id)) \
        .eq("user_id", user_id) \
        .execute()
    
    if not membership.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: caller is not a member of this family"
        )
    return membership.data[0]


def verify_family_admin(
    supabase: Client,
    family_id: UUID,
    user_id: str
) -> dict:
    """Validates that user has ADMIN role in the given family."""
    membership = verify_family_membership(supabase, family_id, user_id)
    if membership.get("role") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only family ADMINs can perform this action"
        )
    return membership
