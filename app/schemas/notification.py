from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID
from enum import Enum


class NotificationType(str, Enum):
    MEDICINE_REMINDER = "MEDICINE_REMINDER"
    EMERGENCY_SOS = "EMERGENCY_SOS"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"


class NotificationBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Short notification title")
    message: str = Field(..., min_length=1, max_length=1000, description="Full notification message text")
    type: NotificationType = Field(..., description="Notification classification")
    scheduled_at: Optional[datetime] = Field(None, description="When notification is scheduled to be delivered")


class NotificationCreate(NotificationBase):
    user_id: UUID = Field(..., description="Target user recipient ID")
    family_member_id: UUID = Field(..., description="Subject family member ID")
    status: NotificationStatus = Field(NotificationStatus.PENDING, description="Initial notification status")


class NotificationUpdate(BaseModel):
    status: Optional[NotificationStatus] = Field(None, description="Updated status, e.g. READ")


class NotificationResponse(NotificationBase):
    id: UUID
    user_id: UUID
    family_member_id: UUID
    status: NotificationStatus
    sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
