"""User administration. Every route needs user:manage (admins only)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.db.models import User
from app.modules.auth import service
from app.modules.auth.schemas import RoleUpdate, UserOut

router = APIRouter(prefix="/users", tags=["users"])

Admin = Annotated[User, Depends(require_permission(Permission.USER_MANAGE))]


@router.patch("/{user_id}/role")
def set_role(user_id: uuid.UUID, body: RoleUpdate, db: DbSession, _: Admin) -> UserOut:
    return UserOut.model_validate(service.set_role(db, user_id, body.role))
