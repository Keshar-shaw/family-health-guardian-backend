from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import date, datetime
from uuid import UUID


class MedicineBase(BaseModel):
    medicine_name: str = Field(..., min_length=1, max_length=150, description="Brand or generic name of medicine")
    dosage: Optional[str] = Field(None, max_length=50, description="Dosage quantity, e.g. 500, 10, 1")
    dosage_unit: Optional[str] = Field(None, max_length=30, description="Unit e.g. mg, ml, drops, tablet")
    frequency: Optional[str] = Field(None, max_length=100, description="Intake frequency e.g. Once daily, Twice daily")
    route: Optional[str] = Field(None, max_length=50, description="Administration route e.g. Oral, Topical, Inhalation")
    start_date: Optional[date] = Field(None, description="Prescription or regimen start date")
    end_date: Optional[date] = Field(None, description="Prescription or regimen end date")
    prescribed_by: Optional[str] = Field(None, max_length=100, description="Prescribing physician or specialist")
    instructions: Optional[str] = Field(None, max_length=1000, description="Usage instructions e.g. Take with food")
    is_active: bool = Field(True, description="Whether the medication is currently active")


class MedicineCreate(MedicineBase):
    family_member_id: UUID = Field(..., description="ID of the family member this medicine is prescribed for")


class MedicineUpdate(BaseModel):
    medicine_name: Optional[str] = Field(None, min_length=1, max_length=150)
    dosage: Optional[str] = Field(None, max_length=50)
    dosage_unit: Optional[str] = Field(None, max_length=30)
    frequency: Optional[str] = Field(None, max_length=100)
    route: Optional[str] = Field(None, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    prescribed_by: Optional[str] = Field(None, max_length=100)
    instructions: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = None


class MedicineResponse(MedicineBase):
    id: UUID
    family_member_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
