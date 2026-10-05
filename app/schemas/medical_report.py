from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import date, datetime
from uuid import UUID
from enum import Enum


class ReportType(str, Enum):
    LAB_REPORT = "LAB_REPORT"
    PRESCRIPTION = "PRESCRIPTION"
    IMAGING_SCAN = "IMAGING_SCAN"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    GENERAL = "GENERAL"
    OTHER = "OTHER"


class MedicalReportBase(BaseModel):
    file_name: str
    report_type: str = "GENERAL"
    mime_type: str
    file_size: int
    report_date: date = Field(default_factory=date.today)
    description: Optional[str] = None


class MedicalReportResponse(MedicalReportBase):
    id: UUID
    family_member_id: UUID
    uploaded_by: UUID
    storage_path: str
    created_at: datetime
    download_url: Optional[str] = Field(None, description="Time-limited secure signed URL")

    model_config = ConfigDict(from_attributes=True)
