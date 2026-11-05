from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

OrgRole = Literal["owner", "admin", "member", "viewer"]
ProjectRole = Literal["manager", "editor", "viewer"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(InputModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class PasswordInput(InputModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class MemberInput(InputModel):
    email: EmailStr
    role: OrgRole = "member"


class MemberUpdate(InputModel):
    role: OrgRole
    is_active: bool


class ProjectInput(InputModel):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=10000)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Empty name")
        return value.strip()


class ProjectMemberInput(InputModel):
    user_id: UUID
    role: ProjectRole


class ProjectOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    description: str
    created_by: UUID
    created_at: datetime
    my_role: ProjectRole | None = None
    can_write: bool = False
    can_manage_members: bool = False
