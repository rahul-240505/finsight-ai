import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: str
    size_bytes: int
    page_count: int
    chunk_count: int
    embedding_model: str
    created_at: datetime
