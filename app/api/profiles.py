from fastapi import APIRouter, Depends, HTTPException, status
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.profile import ProfileResponse, ProfileUpdate
from supabase import Client

router = APIRouter(prefix="/profiles", tags=["Profiles"])


@router.get("/me", response_model=ProfileResponse)
def get_my_profile(
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """Retrieve profile of currently authenticated user."""
    res = supabase.table("profiles").select("*").eq("id", current_user.sub).execute()
    if not res.data:
        # Fallback profile creation if database trigger hasn't fired yet
        new_profile = {
            "id": current_user.sub,
            "full_name": current_user.email.split("@")[0] if current_user.email else "User",
        }
        res = supabase.table("profiles").insert(new_profile).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Profile not found")
        return res.data[0]
    return res.data[0]


@router.put("/me", response_model=ProfileResponse)
def update_my_profile(
    profile_data: ProfileUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """Update profile information of currently authenticated user."""
    update_fields = profile_data.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields provided for update")
    
    res = supabase.table("profiles").update(update_fields).eq("id", current_user.sub).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Profile update failed or profile not found")
    return res.data[0]
