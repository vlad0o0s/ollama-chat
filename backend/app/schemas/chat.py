from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from .message import MessageResponse


class ChatBase(BaseModel):
    title: str


class ChatCreate(ChatBase):
    pass


class ChatUpdate(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None


class ChatResponse(ChatBase):
    id: int
    user_id: int
    pinned: bool
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = None
    last_message_at: Optional[datetime] = None
    last_message: Optional[str] = None
    
    model_config = {"from_attributes": True}


class ChatWithMessages(ChatResponse):
    messages: List[MessageResponse] = []

