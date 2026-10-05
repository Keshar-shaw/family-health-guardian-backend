from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException, status
from supabase import Client
from app.schemas.notification import NotificationType, NotificationStatus


class BaseNotificationProvider(ABC):
    """
    Abstract interface for notification providers.
    Enables future integration with external providers (SMS, Push, Email, etc.)
    without hardcoding any specific paid vendor.
    """
    @abstractmethod
    def send(
        self,
        recipient_id: str,
        title: str,
        message: str,
        notification_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Deliver the notification. Returns True if successfully sent, False otherwise."""
        pass


class InMemoryNotificationProvider(BaseNotificationProvider):
    """
    Default pluggable provider that records dispatches in memory.
    Safe for local development and automated testing without external credentials.
    """
    def __init__(self):
        self.dispatched_notifications: List[Dict[str, Any]] = []

    def send(
        self,
        recipient_id: str,
        title: str,
        message: str,
        notification_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        self.dispatched_notifications.append({
            "recipient_id": recipient_id,
            "title": title,
            "message": message,
            "type": notification_type,
            "metadata": metadata or {},
            "dispatched_at": datetime.now(timezone.utc).isoformat()
        })
        return True

    def clear(self):
        self.dispatched_notifications.clear()


# Global provider registry
_active_provider: BaseNotificationProvider = InMemoryNotificationProvider()


def get_notification_provider() -> BaseNotificationProvider:
    """Retrieve current notification provider instance."""
    return _active_provider


def set_notification_provider(provider: BaseNotificationProvider):
    """Register or swap the active notification provider."""
    global _active_provider
    _active_provider = provider


class NotificationService:
    """
    Core notification service orchestrating database persistence,
    status tracking, and delivery via configured provider.
    """

    @staticmethod
    def create_notification(
        supabase: Client,
        user_id: str,
        family_member_id: str,
        notification_type: NotificationType,
        title: str,
        message: str,
        scheduled_at: Optional[datetime] = None,
        dispatch_immediately: bool = True
    ) -> dict:
        """
        Creates a notification record and dispatches it via active provider.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        final_status = NotificationStatus.PENDING.value
        sent_at = None

        # Dispatch via provider if scheduled for immediate release
        if dispatch_immediately:
            provider = get_notification_provider()
            try:
                success = provider.send(
                    recipient_id=str(user_id),
                    title=title,
                    message=message,
                    notification_type=notification_type.value,
                    metadata={"family_member_id": str(family_member_id)}
                )
                final_status = NotificationStatus.SENT.value if success else NotificationStatus.FAILED.value
                sent_at = now_iso if success else None
            except Exception:
                final_status = NotificationStatus.FAILED.value

        notification_data = {
            "user_id": str(user_id),
            "family_member_id": str(family_member_id),
            "type": notification_type.value,
            "title": title,
            "message": message,
            "status": final_status,
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
            "sent_at": sent_at,
            "created_at": now_iso
        }

        # Persist notification row
        res = supabase.table("notifications").insert(notification_data).execute()
        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create notification record"
            )
        return res.data[0]

    @staticmethod
    def send_sos_notifications(
        supabase: Client,
        sos_event: dict,
        family_member_id: UUID,
        triggerer_user_id: str
    ) -> List[dict]:
        """
        Generates emergency SOS notifications for the patient and all members of their family.
        """
        # Fetch family member details
        fm_res = supabase.table("family_members").select("*").eq("id", str(family_member_id)).execute()
        if not fm_res.data:
            return []
        member = fm_res.data[0]
        family_id = member["family_id"]
        patient_user_id = member["user_id"]

        # Find all other family members in the same family to alert
        family_members_res = supabase.table("family_members").select("user_id").eq("family_id", family_id).execute()
        recipients = {m["user_id"] for m in (family_members_res.data or [])}
        recipients.add(patient_user_id)

        notes_info = f" Notes: {sos_event.get('notes')}" if sos_event.get("notes") else ""
        location_info = ""
        if sos_event.get("latitude") and sos_event.get("longitude"):
            location_info = f" Location: ({sos_event['latitude']}, {sos_event['longitude']})."

        title = "EMERGENCY SOS ALERT"
        message = f"Emergency SOS alert has been triggered!{location_info}{notes_info} Please check immediately."

        created_notifications = []
        for recipient_id in recipients:
            notif = NotificationService.create_notification(
                supabase=supabase,
                user_id=recipient_id,
                family_member_id=str(family_member_id),
                notification_type=NotificationType.EMERGENCY_SOS,
                title=title,
                message=message,
                dispatch_immediately=True
            )
            created_notifications.append(notif)

        return created_notifications

    @staticmethod
    def create_medicine_reminder_notification(
        supabase: Client,
        medicine_id: UUID,
        family_member_id: UUID,
        scheduled_time: str,
        medicine_name: str,
        dosage: Optional[str] = None
    ) -> dict:
        """
        Generates a medicine reminder notification for the patient.
        """
        fm_res = supabase.table("family_members").select("user_id").eq("id", str(family_member_id)).execute()
        if not fm_res.data:
            raise HTTPException(status_code=404, detail="Family member not found")
        recipient_user_id = fm_res.data[0]["user_id"]

        dosage_text = f" ({dosage})" if dosage else ""
        title = f"Medicine Reminder: {medicine_name}"
        message = f"Time to take your scheduled dose of {medicine_name}{dosage_text} at {scheduled_time}."

        return NotificationService.create_notification(
            supabase=supabase,
            user_id=recipient_user_id,
            family_member_id=str(family_member_id),
            notification_type=NotificationType.MEDICINE_REMINDER,
            title=title,
            message=message,
            dispatch_immediately=True
        )

    @staticmethod
    def list_user_notifications(
        supabase: Client,
        user_id: str,
        status_filter: Optional[NotificationStatus] = None,
        type_filter: Optional[NotificationType] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[dict]:
        """
        Returns notifications for the authenticated user with optional filters.
        """
        query = supabase.table("notifications").select("*").eq("user_id", user_id)
        if status_filter:
            query = query.eq("status", status_filter.value)
        if type_filter:
            query = query.eq("type", type_filter.value)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        res = query.execute()
        return res.data if res.data else []

    @staticmethod
    def mark_as_read(
        supabase: Client,
        notification_id: UUID,
        user_id: str
    ) -> dict:
        """
        Marks an unread notification as READ, ensuring caller is the recipient.
        """
        existing = supabase.table("notifications").select("*").eq("id", str(notification_id)).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        notif = existing.data[0]
        if notif["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to access this notification")

        update_res = supabase.table("notifications").update({
            "status": NotificationStatus.READ.value
        }).eq("id", str(notification_id)).execute()

        if not update_res.data:
            raise HTTPException(status_code=400, detail="Failed to update notification")
        return update_res.data[0]
