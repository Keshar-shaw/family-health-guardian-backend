from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID
from enum import Enum


class SOSEventStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class SOSEventCreate(BaseModel):
    family_member_id: UUID = Field(..., description="ID of the family member in distress")
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, description="GPS Latitude (-90 to 90)")
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, description="GPS Longitude (-180 to 180)")
    location_accuracy: Optional[float] = Field(None, ge=0.0, description="Estimated accuracy in meters")
    notes: Optional[str] = Field(None, max_length=1000, description="Urgent medical note or context")


class SOSEventStatusUpdate(BaseModel):
    status: SOSEventStatus = Field(..., description="New status: ACKNOWLEDGED, RESOLVED, CANCELLED")
    notes: Optional[str] = Field(None, max_length=1000, description="Resolution or responder action note")


class SOSEventResponse(BaseModel):
    id: UUID
    family_member_id: UUID
    triggered_by: UUID
    status: SOSEventStatus
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_accuracy: Optional[float] = None
    triggered_at: datetime
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None
    notification_dispatched: bool = False
    emergency_contacts_count: int = 0

    model_config = ConfigDict(from_attributes=True)
