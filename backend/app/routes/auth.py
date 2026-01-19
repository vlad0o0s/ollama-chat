from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import logging
import bcrypt
from ..database import get_db
from ..models.user import User
from ..schemas.auth import RegisterRequest, LoginRequest, RegisterResponse, LoginResponse
from ..schemas.user import UserResponse, UserUpdate
from ..auth.jwt import create_access_token
from ..auth.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

# Настройка bcrypt (поддерживает форматы $2a$, $2b$, $2y$ от bcryptjs)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def truncate_password_to_72_bytes(password: str) -> bytes:
    """Обрезает пароль до 72 байт (ограничение bcrypt) и возвращает bytes"""
    password_bytes = password.encode('utf-8')
    if len(password_bytes) <= 72:
        return password_bytes
    
    # Обрезаем до 72 байт
    truncated_bytes = password_bytes[:72]
    
    # Убираем неполные символы в конце (если обрезали посередине UTF-8 последовательности)
    # UTF-8 продолжение байты начинаются с 10xxxxxx (0b10000000)
    while truncated_bytes and (truncated_bytes[-1] & 0b11000000) == 0b10000000:
        truncated_bytes = truncated_bytes[:-1]
    
    return truncated_bytes


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль"""
    try:
        # Проверяем формат хеша
        if not hashed_password or not hashed_password.startswith(('$2a$', '$2b$', '$2y$')):
            return False
            
        # Обрезаем пароль до 72 байт (ограничение bcrypt)
        password_bytes = truncate_password_to_72_bytes(plain_password)
        
        # Используем bcrypt напрямую для проверки, чтобы избежать проблем с passlib
        try:
            # Преобразуем хеш в bytes
            hashed_bytes = hashed_password.encode('utf-8')
            # Проверяем пароль напрямую через bcrypt
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except (ValueError, TypeError) as e:
            # Если прямой вызов не работает, пробуем через passlib
            logger.debug(f"Прямая проверка bcrypt не удалась, используем passlib: {e}")
            # Декодируем bytes обратно в строку для passlib
            password_str = password_bytes.decode('utf-8', errors='ignore')
            return pwd_context.verify(password_str, hashed_password)
    except Exception as e:
        logger.error(f"Ошибка проверки пароля: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Хеширует пароль"""
    # Обрезаем пароль до 72 байт перед хешированием
    password_bytes = truncate_password_to_72_bytes(password)
    
    # Используем bcrypt напрямую для хеширования, чтобы избежать проблем с passlib
    try:
        # Генерируем соль и хешируем
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    except Exception as e:
        # Если прямой вызов не работает, используем passlib
        logger.debug(f"Прямое хеширование bcrypt не удалось, используем passlib: {e}")
        password_str = password_bytes.decode('utf-8', errors='ignore')
        return pwd_context.hash(password_str)


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

