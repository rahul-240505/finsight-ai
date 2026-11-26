"""Dataset rules. Every function takes the current user and only ever touches their rows.

The ownership filter lives in the query itself (WHERE owner_id = :user), not in a check
after loading, so there is no code path that loads someone else's dataset by accident.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.db.models import Dataset, User

MAX_PAGE_SIZE = 100


def create(db: Session, user: User, name: str) -> Dataset:
    dataset = Dataset(owner_id=user.id, name=name)
    db.add(dataset)
    db.commit()
    return dataset


def list_for(db: Session, user: User, limit: int, offset: int) -> list[Dataset]:
    """Offset pagination is fine here: a user has few datasets. Newest first, id breaks ties."""
    stmt = (
        select(Dataset)
        .where(Dataset.owner_id == user.id)
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
        .limit(min(limit, MAX_PAGE_SIZE))
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_owned(db: Session, user: User, dataset_id: uuid.UUID) -> Dataset:
    """404 whether the dataset doesn't exist or belongs to someone else (IDOR protection)."""
    stmt = select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    dataset = db.scalar(stmt)
    if dataset is None:
        raise NotFound()
    return dataset


def delete(db: Session, user: User, dataset_id: uuid.UUID) -> None:
    db.delete(get_owned(db, user, dataset_id))
    db.commit()
