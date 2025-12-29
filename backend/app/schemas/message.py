from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any


class MessageBase(BaseModel):
    role: str
    content: str
    message_type: str = "text"
    image_url: Optional[str] = None
    image_metadata: Optional[Dict[str, Any]] = None


class MessageCreate(MessageBase):
    pass


class MessageUpdate(BaseModel):
    content: str


class MessageResponse(MessageBase):
    id: int
    chat_id: int
    created_at: datetime
    deleted: bool = False
    edited: bool = False
    edited_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}

