from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID


class HealthRecordBase(BaseModel):
    blood_group: Optional[str] = Field(None, max_length=20, description="Blood group e.g. A+, O-, B+")
    allergies: Optional[str] = Field(None, max_length=1000, description="Known allergies")
    chronic_conditions: Optional[str] = Field(None, max_length=1000, description="Chronic medical conditions")
    medical_history: Optional[str] = Field(None, max_length=2000, description="Past surgeries, conditions, medical events")
    current_conditions: Optional[str] = Field(None, max_length=1000, description="Current health issues/symptoms")
    doctor_name: Optional[str] = Field(None, max_length=100, description="Primary attending doctor name")
    doctor_contact: Optional[str] = Field(None, max_length=50, description="Doctor contact phone or email")
    notes: Optional[str] = Field(None, max_length=2000, description="Additional health or dietary notes")


class HealthRecordCreate(HealthRecordBase):
    family_member_id: UUID = Field(..., description="ID of the family member this health record belongs to")


class HealthRecordUpdate(BaseModel):
    blood_group: Optional[str] = Field(None, max_length=20)
    allergies: Optional[str] = Field(None, max_length=1000)
    chronic_conditions: Optional[str] = Field(None, max_length=1000)
    medical_history: Optional[str] = Field(None, max_length=2000)
    current_conditions: Optional[str] = Field(None, max_length=1000)
    doctor_name: Optional[str] = Field(None, max_length=100)
    doctor_contact: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, max_length=2000)


class HealthRecordResponse(HealthRecordBase):
    id: UUID
    family_member_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
