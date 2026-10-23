from pydantic import BaseModel, Field


class EventCenterIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=50)
    topics: dict[str, int | str | None] = Field(default_factory=dict)  # {"payments": 12, ...}; empty value = General
    is_enabled: bool = True
    note: str | None = Field(default=None, max_length=300)
