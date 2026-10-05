from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Optional, Any
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
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, description="GPS Latitude (-90.0 to 90.0)")
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, description="GPS Longitude (-180.0 to 180.0)")
    accuracy: Optional[float] = Field(None, ge=0.0, description="Estimated accuracy in meters")
    location_accuracy: Optional[float] = Field(None, ge=0.0, description="Estimated accuracy in meters (legacy alias)")
    timestamp: Optional[datetime] = Field(None, description="Optional GPS fix capture timestamp")
    location_timestamp: Optional[datetime] = Field(None, description="Optional GPS capture timestamp (legacy alias)")
    notes: Optional[str] = Field(None, max_length=1000, description="Urgent medical note or context")

    @model_validator(mode="before")
    @classmethod
    def validate_and_normalize_location(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize accuracy and location_accuracy
            acc = data.get("accuracy") if data.get("accuracy") is not None else data.get("location_accuracy")
            if acc is not None:
                data["accuracy"] = acc
                data["location_accuracy"] = acc

            # Normalize timestamp and location_timestamp
            ts = data.get("timestamp") if data.get("timestamp") is not None else data.get("location_timestamp")
            if ts is not None:
                data["timestamp"] = ts
                data["location_timestamp"] = ts

            lat = data.get("latitude")
            lon = data.get("longitude")
            # If one coordinate is given, both must be present
            if (lat is not None and lon is None) or (lon is not None and lat is None):
                raise ValueError("Both latitude and longitude must be provided together when specifying location")
        return data


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
    accuracy: Optional[float] = None
    location_accuracy: Optional[float] = None
    timestamp: Optional[datetime] = None
    location_timestamp: Optional[datetime] = None
    triggered_at: datetime
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None
    notification_dispatched: bool = False
    emergency_contacts_count: int = 0

    @model_validator(mode="before")
    @classmethod
    def populate_response_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            acc = data.get("accuracy") if data.get("accuracy") is not None else data.get("location_accuracy")
            data["accuracy"] = acc
            data["location_accuracy"] = acc

            ts = data.get("timestamp") or data.get("location_timestamp")
            data["timestamp"] = ts
            data["location_timestamp"] = ts
        return data

    model_config = ConfigDict(from_attributes=True)
