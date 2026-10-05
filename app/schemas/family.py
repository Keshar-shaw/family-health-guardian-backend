from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum


class FamilyRole(str, Enum):
    ADMIN = "ADMIN"
    GUARDIAN = "GUARDIAN"
    MEMBER = "MEMBER"


class FamilyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class FamilyCreate(FamilyBase):
    pass


class FamilyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class FamilyMemberAdd(BaseModel):
    user_id: UUID
    role: FamilyRole = FamilyRole.MEMBER


class FamilyMemberResponse(BaseModel):
    id: UUID
    family_id: UUID
    user_id: UUID
    role: FamilyRole
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FamilyResponse(FamilyBase):
    id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    members: Optional[List[FamilyMemberResponse]] = []

    model_config = ConfigDict(from_attributes=True)
