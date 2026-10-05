from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID
import re


class EmergencyContactBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Full name of emergency contact")
    relationship: Optional[str] = Field(None, max_length=50, description="Relationship e.g. Parent, Spouse, Physician")
    phone: str = Field(..., min_length=5, max_length=30, description="Primary contact phone number")
    email: Optional[str] = Field(None, max_length=100, description="Optional email address")
    priority: int = Field(1, ge=1, le=10, description="Priority rank e.g. 1 (primary), 2 (secondary)")
    is_active: bool = Field(True, description="Whether contact is active")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)\.]", "", v)
        if not re.match(r"^\+?[0-9]{5,20}$", cleaned):
            raise ValueError("Phone number must contain between 5 and 20 numeric digits")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "":
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
                raise ValueError("Invalid email format")
        return v


class EmergencyContactCreate(EmergencyContactBase):
    family_member_id: UUID = Field(..., description="ID of the family member this emergency contact belongs to")


class EmergencyContactUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    relationship: Optional[str] = Field(None, max_length=50)
    phone: Optional[str] = Field(None, min_length=5, max_length=30)
    email: Optional[str] = Field(None, max_length=100)
    priority: Optional[int] = Field(None, ge=1, le=10)
    is_active: Optional[bool] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = re.sub(r"[\s\-\(\)\.]", "", v)
            if not re.match(r"^\+?[0-9]{5,20}$", cleaned):
                raise ValueError("Phone number must contain between 5 and 20 numeric digits")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "":
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
                raise ValueError("Invalid email format")
        return v


class EmergencyContactResponse(EmergencyContactBase):
    id: UUID
    family_member_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
