from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID
from enum import Enum


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    DENIED = "DENIED"


class ConsentPermission(str, Enum):
    READ_ONLY = "READ_ONLY"
    FULL_ACCESS = "FULL_ACCESS"


class ConsentCreate(BaseModel):
    grantee_id: UUID  # The guardian/family member being given access
    family_id: UUID
    permission_level: ConsentPermission = ConsentPermission.READ_ONLY
    notes: Optional[str] = Field(None, max_length=255)


class ConsentUpdate(BaseModel):
    status: ConsentStatus
    permission_level: Optional[ConsentPermission] = None
    notes: Optional[str] = None


class ConsentResponse(BaseModel):
    id: UUID
    granter_id: UUID
    grantee_id: UUID
    family_id: UUID
    permission_level: ConsentPermission
    status: ConsentStatus
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
