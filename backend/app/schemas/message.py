from pydantic import BaseModel
from datetime import datetime


class MessageBase(BaseModel):
    role: str
    content: str


class MessageCreate(MessageBase):
    pass


class MessageResponse(MessageBase):
    id: int
    chat_id: int
    created_at: datetime
    
    model_config = {"from_attributes": True}

