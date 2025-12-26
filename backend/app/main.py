from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
from .config import settings
from .database import init_db
from .routes import auth, chats, admin
from .models.user import User
from .database import get_db, SessionLocal

app = FastAPI(
    title="Ollama Chat API",
    description="Backend API для чат-приложения с Ollama",
    version="1.0.0-beta.1"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение роутов
app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(admin.router)


@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске"""
    # Инициализация базы данных
    init_db()
    
    # Назначаем пользователя vlad0o0s администратором при запуске сервера
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.name == "vlad0o0s").first()
        if user:
            if user.role != "admin":
                user.role = "admin"
                db.commit()
                print("✅ Пользователь vlad0o0s назначен администратором")
            else:
                print("✅ Пользователь vlad0o0s уже является администратором")
        else:
            print("⚠️ Пользователь vlad0o0s не найден в базе данных")
    except Exception as e:
        print(f"❌ Ошибка назначения админа: {e}")
        db.rollback()
    finally:
        db.close()


@app.get("/")
async def root():
    """Корневой endpoint"""
    return {"message": "Ollama Chat API", "version": "1.0.0-beta.1"}


@app.get("/health")
async def health_check():
    """Проверка здоровья сервера"""
    return {"status": "ok"}


# Обслуживание статических файлов React приложения (если build папка существует)
build_path = Path("../lastV/build")
if build_path.exists():
    app.mount("/static", StaticFiles(directory=str(build_path / "static")), name="static")
    
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        """Все остальные маршруты направляем на React приложение"""
        if full_path.startswith("api") or full_path.startswith("static"):
            return {"error": "Not found"}
        
        index_path = build_path / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"error": "React app not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )

