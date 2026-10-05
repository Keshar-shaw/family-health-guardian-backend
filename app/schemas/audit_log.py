from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


class AuditAction(str, Enum):
    HEALTH_RECORD_CREATED = "HEALTH_RECORD_CREATED"
    HEALTH_RECORD_VIEWED = "HEALTH_RECORD_VIEWED"
    HEALTH_RECORD_UPDATED = "HEALTH_RECORD_UPDATED"
    HEALTH_RECORD_DELETED = "HEALTH_RECORD_DELETED"
    MEDICINE_CREATED = "MEDICINE_CREATED"
    MEDICINE_UPDATED = "MEDICINE_UPDATED"
    MEDICAL_REPORT_UPLOADED = "MEDICAL_REPORT_UPLOADED"
    MEDICAL_REPORT_DELETED = "MEDICAL_REPORT_DELETED"
    SOS_TRIGGERED = "SOS_TRIGGERED"
    SOS_STATUS_CHANGED = "SOS_STATUS_CHANGED"
    EMERGENCY_CONTACT_CHANGED = "EMERGENCY_CONTACT_CHANGED"


class AuditResourceType(str, Enum):
    HEALTH_RECORD = "HEALTH_RECORD"
    MEDICINE = "MEDICINE"
    MEDICAL_REPORT = "MEDICAL_REPORT"
    SOS_EVENT = "SOS_EVENT"
    EMERGENCY_CONTACT = "EMERGENCY_CONTACT"


class AuditLogBase(BaseModel):
    action: str = Field(..., description="Action name e.g. HEALTH_RECORD_CREATED")
    resource_type: str = Field(..., description="Type of target resource")
    resource_id: Optional[UUID] = Field(None, description="Identifier of target entity")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Sanitized non-sensitive contextual metadata")


class AuditLogCreate(AuditLogBase):
    actor_user_id: UUID
    family_id: Optional[UUID] = None
    family_member_id: Optional[UUID] = None


class AuditLogResponse(AuditLogBase):
    id: UUID
    actor_user_id: UUID
    family_id: Optional[UUID] = None
    family_member_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
