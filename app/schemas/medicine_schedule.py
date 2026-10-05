from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID


class MedicineScheduleBase(BaseModel):
    scheduled_time: str = Field(..., min_length=1, max_length=50, description="Scheduled time e.g. 08:00 AM, 14:00")
    frequency_type: str = Field("DAILY", max_length=50, description="Frequency type e.g. DAILY, WEEKLY, AS_NEEDED")
    days_of_week: Optional[List[str]] = Field(None, description="Days of week e.g. ['MON', 'WED', 'FRI']")
    start_date: Optional[date] = Field(None, description="Schedule start date")
    end_date: Optional[date] = Field(None, description="Schedule end date")
    reminder_enabled: bool = Field(True, description="Whether notification/reminder is active")


class MedicineScheduleCreate(MedicineScheduleBase):
    medicine_id: UUID = Field(..., description="ID of the medicine this schedule belongs to")


class MedicineScheduleUpdate(BaseModel):
    scheduled_time: Optional[str] = Field(None, min_length=1, max_length=50)
    frequency_type: Optional[str] = Field(None, max_length=50)
    days_of_week: Optional[List[str]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reminder_enabled: Optional[bool] = None


class MedicineScheduleResponse(MedicineScheduleBase):
    id: UUID
    medicine_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
