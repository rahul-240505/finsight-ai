"""Request and response models for auth and user management."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.permissions import Role


class Credentials(BaseModel):
    email: EmailStr
    # Upper bound stops someone making the server hash megabytes of "password".
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    # No min_length on login: a short password is simply wrong, not a validation error
    # (a 422 would tell an attacker about the policy and skip the timing equaliser).
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: Role
    created_at: datetime


class RoleUpdate(BaseModel):
    role: Role
