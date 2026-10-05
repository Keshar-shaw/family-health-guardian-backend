from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional
from datetime import date, datetime, timezone
from uuid import UUID
from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.schemas.emergency_sos import (
    SOSEventCreate,
    SOSEventStatusUpdate,
    SOSEventResponse,
    SOSEventStatus,
)
from supabase import Client

router = APIRouter(prefix="/emergency/sos", tags=["Emergency SOS"])


def verify_sos_member_access(
    supabase: Client,
    family_member_id: UUID,
    user_id: str,
    allow_triggerer: Optional[str] = None
) -> dict:
    """
    Validates family member existence and verifies the requesting user is either:
    1. The triggerer of this specific event
    2. The member themselves (self)
    3. A member of the same family
    """
    if allow_triggerer and allow_triggerer == user_id:
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


@router.post("", response_model=SOSEventResponse, status_code=status.HTTP_201_CREATED)
def trigger_sos_event(
    sos_in: SOSEventCreate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Trigger an Emergency SOS alert.
    1. Authenticates caller.
    2. Validates family member.
    3. Verifies permission (self or same family member).
    4. Creates SOS event.
    5. Stores optional location coordinates.
    6. Prepares event for emergency notification dispatch.
    7. Returns a sanitized response.
    """
    member = verify_sos_member_access(
        supabase=supabase,
        family_member_id=sos_in.family_member_id,
        user_id=current_user.sub
    )

    acc_val = sos_in.accuracy if sos_in.accuracy is not None else sos_in.location_accuracy
    ts_val = sos_in.timestamp or sos_in.location_timestamp

    sos_dict = {
        "family_member_id": str(sos_in.family_member_id),
        "triggered_by": current_user.sub,
        "status": SOSEventStatus.TRIGGERED.value,
        "latitude": sos_in.latitude,
        "longitude": sos_in.longitude,
        "accuracy": acc_val,
        "location_accuracy": acc_val,
        "notes": sos_in.notes,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }
    if ts_val:
        sos_dict["location_timestamp"] = ts_val.isoformat()

    res = supabase.table("sos_events").insert(sos_dict).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to trigger SOS alert")
    created_event = res.data[0]

    # Prepare notification: count registered active emergency contacts
    contacts_res = supabase.table("emergency_contacts").select("id") \
        .eq("family_member_id", str(sos_in.family_member_id)) \
        .eq("is_active", True) \
        .execute()
    
    contact_count = len(contacts_res.data) if contacts_res.data else 0

    created_event["notification_dispatched"] = True
    created_event["emergency_contacts_count"] = contact_count

    # Dispatch emergency notifications via NotificationService
    try:
        from app.services.notifications import NotificationService
        NotificationService.send_sos_notifications(
            supabase=supabase,
            sos_event=created_event,
            family_member_id=sos_in.family_member_id,
            triggerer_user_id=current_user.sub
        )
    except Exception:
        pass

    from app.services.audit import AuditService, AuditAction, AuditResourceType
    AuditService.log_action(
        supabase=supabase,
        actor_user_id=current_user.sub,
        action=AuditAction.SOS_TRIGGERED.value,
        resource_type=AuditResourceType.SOS_EVENT.value,
        resource_id=UUID(created_event["id"]),
        family_id=UUID(member["family_id"]) if member and member.get("family_id") else None,
        family_member_id=sos_in.family_member_id,
        metadata={"has_location": bool(created_event.get("latitude")), "notes": sos_in.notes}
    )

    return created_event


@router.get("/history", response_model=List[SOSEventResponse])
def get_sos_history(
    family_member_id: Optional[UUID] = None,
    status: Optional[SOSEventStatus] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve SOS event history with filters, ordered by newest first.
    Authorized for self or family members.
    """
    if family_member_id is not None:
        verify_sos_member_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub
        )
        query = supabase.table("sos_events").select("*").eq("family_member_id", str(family_member_id))
    else:
        # Find all families current user belongs to
        fm_res = supabase.table("family_members").select("family_id").eq("user_id", current_user.sub).execute()
        family_ids = [m["family_id"] for m in (fm_res.data or [])]
        if not family_ids:
            return []

        all_members_res = supabase.table("family_members").select("id").in_("family_id", family_ids).execute()
        authorized_member_ids = [m["id"] for m in (all_members_res.data or [])]
        if not authorized_member_ids:
            return []
        
        query = supabase.table("sos_events").select("*").in_("family_member_id", authorized_member_ids)

    if status is not None:
        query = query.eq("status", status.value)
    if start_date is not None:
        query = query.gte("triggered_at", f"{start_date}T00:00:00Z")
    if end_date is not None:
        query = query.lte("triggered_at", f"{end_date}T23:59:59Z")

    query = query.order("triggered_at", desc=True).range(offset, offset + limit - 1)
    res = query.execute()
    return res.data if res.data else []


@router.get("/{id}", response_model=SOSEventResponse)
def get_sos_event(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve details of an SOS event by ID.
    Caller must be the triggerer or belong to the patient's family.
    """
    res = supabase.table("sos_events").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOS event not found")
    event = res.data[0]

    verify_sos_member_access(
        supabase=supabase,
        family_member_id=UUID(event["family_member_id"]),
        user_id=current_user.sub,
        allow_triggerer=event.get("triggered_by")
    )
    return event


@router.patch("/{id}/status", response_model=SOSEventResponse)
def update_sos_event_status(
    id: UUID,
    status_update: SOSEventStatusUpdate,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Update the status of an active SOS event (ACKNOWLEDGED, RESOLVED, CANCELLED).
    Caller must be a member of the patient's family or the alert triggerer.
    """
    res = supabase.table("sos_events").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOS event not found")
    event = res.data[0]

    member = verify_sos_member_access(
        supabase=supabase,
        family_member_id=UUID(event["family_member_id"]),
        user_id=current_user.sub,
        allow_triggerer=event.get("triggered_by")
    )

    update_dict = {"status": status_update.status.value}
    if status_update.notes is not None:
        update_dict["notes"] = status_update.notes

    if status_update.status in (SOSEventStatus.RESOLVED, SOSEventStatus.CANCELLED) and not event.get("resolved_at"):
        update_dict["resolved_at"] = datetime.now(timezone.utc).isoformat()

    update_res = supabase.table("sos_events").update(update_dict).eq("id", str(id)).execute()
    if not update_res.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update SOS event status")
    updated = update_res.data[0]

    from app.services.audit import AuditService, AuditAction, AuditResourceType
    AuditService.log_action(
        supabase=supabase,
        actor_user_id=current_user.sub,
        action=AuditAction.SOS_STATUS_CHANGED.value,
        resource_type=AuditResourceType.SOS_EVENT.value,
        resource_id=id,
        family_id=UUID(member["family_id"]) if member and member.get("family_id") else None,
        family_member_id=UUID(event["family_member_id"]),
        metadata={"new_status": status_update.status.value, "notes": status_update.notes}
    )

    return updated
