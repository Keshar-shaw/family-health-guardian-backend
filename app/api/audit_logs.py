from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import List, Optional
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.auth.authorization import verify_family_member_access, verify_family_membership
from app.schemas.audit_log import AuditLogResponse
from app.services.audit import AuditService
from supabase import Client

router = APIRouter(prefix="/audit-logs", tags=["Audit Trail"])


@router.get("", response_model=List[AuditLogResponse])
def get_audit_logs(
    family_id: Optional[UUID] = Query(None, description="Filter logs for a specific family"),
    family_member_id: Optional[UUID] = Query(None, description="Filter logs for a specific family member"),
    action: Optional[str] = Query(None, description="Filter by action name e.g. HEALTH_RECORD_VIEWED"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type e.g. HEALTH_RECORD"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve immutable audit log history.
    Caller must be a member of the requested family or authorized for the requested member.
    """
    if family_id is not None:
        verify_family_membership(supabase, family_id, current_user.sub)

    if family_member_id is not None:
        verify_family_member_access(supabase, family_member_id, current_user.sub, require_full_access=False)

    actor_filter = None
    if family_id is None and family_member_id is None:
        # Default to caller's own actions if no specific family scope is requested
        actor_filter = current_user.sub

    return AuditService.list_logs(
        supabase=supabase,
        actor_user_id=actor_filter,
        family_id=family_id,
        family_member_id=family_member_id,
        action=action,
        resource_type=resource_type,
        limit=limit,
        offset=offset
    )
