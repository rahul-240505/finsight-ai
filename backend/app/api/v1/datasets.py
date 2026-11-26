"""Dataset routes. Permission checks here; ownership checks in the service."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.db.models import User
from app.modules.datasets import service

router = APIRouter(prefix="/datasets", tags=["datasets"])

Reader = Annotated[User, Depends(require_permission(Permission.DATASET_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.DATASET_WRITE))]


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


@router.post("", status_code=status.HTTP_201_CREATED)
def create_dataset(body: DatasetCreate, db: DbSession, user: Writer) -> DatasetOut:
    return DatasetOut.model_validate(service.create(db, user, body.name))


@router.get("")
def list_datasets(
    db: DbSession,
    user: Reader,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DatasetOut]:
    """Offset pagination: `limit` (max 100) and `offset`."""
    return [DatasetOut.model_validate(d) for d in service.list_for(db, user, limit, offset)]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID, db: DbSession, user: Reader) -> DatasetOut:
    return DatasetOut.model_validate(service.get_owned(db, user, dataset_id))


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: uuid.UUID, db: DbSession, user: Writer) -> None:
    service.delete(db, user, dataset_id)
