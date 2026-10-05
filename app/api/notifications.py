from fastapi import APIRouter, Depends, Query, status
from typing import List, Optional
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.notification import (
    NotificationResponse,
    NotificationStatus,
    NotificationType,
)
from app.services.notifications import NotificationService
from supabase import Client

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=List[NotificationResponse])
def get_my_notifications(
    status_filter: Optional[NotificationStatus] = Query(None, alias="status", description="Filter by status (PENDING, SENT, FAILED, READ)"),
    type_filter: Optional[NotificationType] = Query(None, alias="type", description="Filter by type (MEDICINE_REMINDER, EMERGENCY_SOS)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve notification feed for current user.
    """
    return NotificationService.list_user_notifications(
        supabase=supabase,
        user_id=current_user.sub,
        status_filter=status_filter,
        type_filter=type_filter,
        limit=limit,
        offset=offset
    )


@router.patch("/{id}/read", response_model=NotificationResponse)
def mark_notification_read(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Mark a specific notification as READ.
    Caller must be the notification recipient.
    """
    return NotificationService.mark_as_read(
        supabase=supabase,
        notification_id=id,
        user_id=current_user.sub
    )
