from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from pydantic import BaseModel
from ..database import get_db
from ..models.user import User
from ..models.chat import Chat
from ..schemas.user import UserResponse
from ..auth.dependencies import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


class MakeAdminRequest(BaseModel):
    username: str


class UpdateRoleRequest(BaseModel):
    role: str


@router.post("/make-admin")
async def make_admin(
    request: MakeAdminRequest,
    db: Session = Depends(get_db)
):
    """Временный endpoint для назначения админа (для отладки)"""
    if not request.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Имя пользователя обязательно"
        )
    
    user = db.query(User).filter(User.name == request.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    user.role = "admin"
    db.commit()
    
    return {"message": f"Пользователь {request.username} назначен администратором"}


@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Получение всех пользователей (только для админов)"""
    users = db.query(
        User,
        func.count(Chat.id).label("chat_count")
    ).outerjoin(Chat, User.id == Chat.user_id)\
     .group_by(User.id)\
     .order_by(User.created_at.desc())\
     .all()
    
    result = []
    for user, chat_count in users:
        user_dict = {
            "id": user.id,
            "name": user.name,
            "role": user.role,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "chat_count": chat_count or 0
        }
        result.append(UserResponse(**user_dict))
    
    return result


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    request: UpdateRoleRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Изменение роли пользователя (только для админов)"""
    # Валидация роли
    if not request.role or request.role not in ["user", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недопустимая роль"
        )
    
    # Проверяем, что пользователь не пытается изменить свою роль
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя изменить свою собственную роль"
        )
    
    # Проверяем, существует ли пользователь
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    user.role = request.role
    db.commit()
    
    return {"message": "Роль пользователя успешно изменена"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Удаление пользователя (только для админов)"""
    # Проверяем, что пользователь не пытается удалить себя
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя удалить самого себя"
        )
    
    # Проверяем, существует ли пользователь
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    db.delete(user)
    db.commit()
    
    return {"message": "Пользователь успешно удален"}

