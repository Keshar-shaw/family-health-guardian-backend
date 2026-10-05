from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.family import (
    FamilyCreate,
    FamilyUpdate,
    FamilyResponse,
    FamilyMemberAdd,
    FamilyMemberResponse,
    FamilyRole
)
from supabase import Client

router = APIRouter(prefix="/families", tags=["Families & Members"])


@router.post("", response_model=FamilyResponse, status_code=status.HTTP_201_CREATED)
def create_family(
    family_in: FamilyCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """Create a new family and automatically add creator as ADMIN."""
    family_dict = family_in.model_dump()
    family_dict["created_by"] = current_user.sub

    res = supabase.table("families").insert(family_dict).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create family")
    
    family = res.data[0]

    # Add creator as ADMIN member
    member_data = {
        "family_id": family["id"],
        "user_id": current_user.sub,
        "role": FamilyRole.ADMIN.value
    }
    member_res = supabase.table("family_members").insert(member_data).execute()
    family["members"] = member_res.data if member_res.data else []

    return family


@router.get("", response_model=List[FamilyResponse])
def list_my_families(
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """List all families current user belongs to."""
    # Fetch family memberships
    fm_res = supabase.table("family_members").select("family_id").eq("user_id", current_user.sub).execute()
    if not fm_res.data:
        return []

    family_ids = [m["family_id"] for m in fm_res.data]
    families_res = supabase.table("families").select("*").in_("id", family_ids).execute()
    return families_res.data if families_res.data else []


@router.get("/{family_id}", response_model=FamilyResponse)
def get_family_details(
    family_id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """Get details and members of a specific family."""
    # Backend authorization: verify caller is a member of this family
    member_check = supabase.table("family_members").select("id") \
        .eq("family_id", str(family_id)) \
        .eq("user_id", current_user.sub) \
        .execute()
    if not member_check.data:
        raise HTTPException(status_code=403, detail="Access denied: you are not a member of this family")

    fam_res = supabase.table("families").select("*").eq("id", str(family_id)).execute()
    if not fam_res.data:
        raise HTTPException(status_code=404, detail="Family not found or access denied")
    
    family = fam_res.data[0]
    members_res = supabase.table("family_members").select("*").eq("family_id", str(family_id)).execute()
    family["members"] = members_res.data if members_res.data else []

    return family


@router.post("/{family_id}/members", response_model=FamilyMemberResponse, status_code=status.HTTP_201_CREATED)
def add_family_member(
    family_id: UUID,
    member_in: FamilyMemberAdd,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """Add a new member to the family (ADMIN role required)."""
    # Check if current user is ADMIN
    admin_check = supabase.table("family_members") \
        .select("role") \
        .eq("family_id", str(family_id)) \
        .eq("user_id", current_user.sub) \
        .execute()
    
    if not admin_check.data or admin_check.data[0]["role"] != FamilyRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Only family ADMINs can add members")

    member_data = {
        "family_id": str(family_id),
        "user_id": str(member_in.user_id),
        "role": member_in.role.value
    }

    res = supabase.table("family_members").insert(member_data).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to add member to family")
    return res.data[0]


@router.delete("/{family_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_family_member(
    family_id: UUID,
    user_id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """Remove a member from the family (Self removal or ADMIN removal)."""
    # Check if self removal or admin removal
    if current_user.sub != str(user_id):
        admin_check = supabase.table("family_members") \
            .select("role") \
            .eq("family_id", str(family_id)) \
            .eq("user_id", current_user.sub) \
            .execute()
        
        if not admin_check.data or admin_check.data[0]["role"] != FamilyRole.ADMIN.value:
            raise HTTPException(status_code=403, detail="Only family ADMINs or self can remove members")

    res = supabase.table("family_members") \
        .delete() \
        .eq("family_id", str(family_id)) \
        .eq("user_id", str(user_id)) \
        .execute()
    
    return None
