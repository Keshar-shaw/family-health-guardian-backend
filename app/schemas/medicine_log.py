from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID
from enum import Enum


class MedicineLogStatus(str, Enum):
    TAKEN = "TAKEN"
    MISSED = "MISSED"
    SKIPPED = "SKIPPED"


class MedicineLogBase(BaseModel):
    scheduled_at: Optional[datetime] = Field(None, description="Expected time the medicine was scheduled to be taken")
    taken_at: Optional[datetime] = Field(None, description="Actual time medicine was ingested")
    status: MedicineLogStatus = Field(MedicineLogStatus.TAKEN, description="Status: TAKEN, MISSED, SKIPPED")
    notes: Optional[str] = Field(None, max_length=1000, description="Notes on reaction, reasons for skipping, etc.")


class MedicineLogCreate(MedicineLogBase):
    medicine_id: UUID = Field(..., description="ID of the parent medicine")
    schedule_id: Optional[UUID] = Field(None, description="Optional ID of associated schedule")
    family_member_id: Optional[UUID] = Field(None, description="Optional family member ID (defaults to medicine's family member)")


class MedicineLogStatusUpdate(BaseModel):
    status: MedicineLogStatus = Field(..., description="Updated status: TAKEN, MISSED, SKIPPED")
    taken_at: Optional[datetime] = Field(None, description="Optional timestamp when taken")
    notes: Optional[str] = Field(None, max_length=1000, description="Optional update notes")


class MedicineLogResponse(MedicineLogBase):
    id: UUID
    medicine_id: UUID
    schedule_id: Optional[UUID] = None
    family_member_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
