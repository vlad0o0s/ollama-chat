from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from ..database import get_db
from ..models.user import User
from ..schemas.auth import RegisterRequest, LoginRequest, RegisterResponse, LoginResponse
from ..schemas.user import UserResponse, UserUpdate
from ..auth.jwt import create_access_token
from ..auth.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Настройка bcrypt (поддерживает форматы $2a$, $2b$, $2y$ от bcryptjs)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль"""
    try:
        # Ограничение bcrypt - пароль не может быть длиннее 72 байта
        if len(plain_password.encode('utf-8')) > 72:
            plain_password = plain_password[:72]
        
        # Проверяем формат хеша
        if not hashed_password or not hashed_password.startswith(('$2a$', '$2b$', '$2y$')):
            return False
            
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"❌ Ошибка проверки пароля: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Хеширует пароль"""
    return pwd_context.hash(password)


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Регистрация нового пользователя"""
    # Валидация
    if not request.name or not request.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Все поля обязательны"
        )
    
    if len(request.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль должен содержать минимум 6 символов"
        )
    
    # Проверяем, существует ли пользователь
    existing_user = db.query(User).filter(User.name == request.name).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким именем уже существует"
        )
    
    # Хешируем пароль
    hashed_password = get_password_hash(request.password)
    
    # Создаем пользователя
    new_user = User(name=request.name, password=hashed_password, role="user")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Создаем JWT токен
    token = create_access_token(
        data={"userId": new_user.id, "name": new_user.name, "role": new_user.role}
    )
    
    return RegisterResponse(
        message="Пользователь успешно зарегистрирован",
        token=token,
        user=UserResponse.model_validate(new_user)
    )


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Вход в систему"""
    # Валидация
    if not request.name or not request.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Имя пользователя и пароль обязательны"
        )
    
    # Находим пользователя
    user = db.query(User).filter(User.name == request.name).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    # Проверяем пароль
    if not verify_password(request.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    # Создаем JWT токен
    token = create_access_token(
        data={"userId": user.id, "name": user.name, "role": user.role}
    )
    
    return LoginResponse(
        message="Успешный вход",
        token=token,
        user=UserResponse.model_validate(user)
    )


@router.get("/verify", response_model=UserResponse)
async def verify_token(current_user: User = Depends(get_current_user)):
    """Проверка токена"""
    return UserResponse.model_validate(current_user)


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление профиля пользователя"""
    # Проверяем, не занято ли имя другим пользователем
    if user_update.name and user_update.name != current_user.name:
        user_with_same_name = db.query(User).filter(User.name == user_update.name).first()
        if user_with_same_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя уже используется"
            )
    
    # Обновляем данные
    if user_update.name:
        current_user.name = user_update.name
    db.commit()
    db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)

