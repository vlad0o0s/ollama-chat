from pydantic import BaseModel
from .user import UserResponse


class RegisterRequest(BaseModel):
    name: str
    password: str


class LoginRequest(BaseModel):
    name: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    message: str
    token: str
    user: UserResponse


class LoginResponse(BaseModel):
    message: str
    token: str
    user: UserResponse

