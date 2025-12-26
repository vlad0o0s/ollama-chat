from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    name: str


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None


class UserResponse(UserBase):
    id: int
    role: str
    created_at: datetime
    updated_at: datetime
    chat_count: Optional[int] = None
    
    model_config = {"from_attributes": True}


class UserInDB(UserResponse):
    password: str
