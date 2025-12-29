from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    # JWT
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_DAYS: int = 7
    
    # Database - MySQL (основная БД)
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "ollama_chat"
    DB_USE_MYSQL: bool = True
    
    # SQLite (только для совместимости, не используется)
    DATABASE_URL: str = "sqlite:///./data/ollama_chat.db"
    
    # Server
    PORT: int = 5000
    HOST: str = "0.0.0.0"
    
    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5000"
    
    # Tavily Search API
    TAVILY_API_KEY: str = ""
    TAVILY_SEARCH_DEPTH: str = "basic"  # "basic" or "advanced"
    TAVILY_MAX_RESULTS: int = 5
    TAVILY_SEARCH_TIMEOUT: int = 10  # seconds
    
    # Ollama Configuration
    OLLAMA_URL: str = "http://192.168.10.12:11434"
    OLLAMA_DEFAULT_MODEL: str = "gpt-oss:20b"
    
    # ComfyUI Configuration
    COMFYUI_URL: str = ""  # URL ComfyUI сервера (обязательно указать в .env)
    COMFYUI_MODEL: str = "flux1-dev-fp8"
    COMFYUI_TIMEOUT: int = 300  # секунд (5 минут)
    COMFYUI_RETRY_ATTEMPTS: int = 3
    COMFYUI_WORKFLOW_PATH: str = r"C:\ComfyUI_windows_portable\ComfyUI\Flux.json"  # Путь к JSON workflow шаблону
    
    # Image Storage Configuration
    IMAGE_STORAGE_PATH: str = "static/images"
    IMAGE_DEFAULT_WIDTH: int = 1024
    IMAGE_DEFAULT_HEIGHT: int = 1024
    
    # GPU Resource Management
    GPU_MONITOR_ENABLED: bool = True
    GPU_MONITOR_INTERVAL: int = 2  # секунды между проверками
    GPU_VRAM_THRESHOLD: int = 90  # процент использования VRAM для блокировки
    GPU_MIN_FREE_VRAM_MB: int = 1024  # минимум свободной VRAM для новых задач (уменьшено, так как процессы переключаются)
    GPU_WAIT_TIMEOUT: int = 300  # таймаут ожидания GPU (секунды)
    GPU_PRIORITY_COMFYUI: int = 10  # приоритет ComfyUI (высший)
    GPU_PRIORITY_OLLAMA: int = 5  # приоритет Ollama (средний)
    
    # Process Management API
    PROCESS_MANAGER_API_URL: str = "http://localhost:8888"  # URL Process Management API (локальный сервер)
    PROCESS_SWITCH_TIMEOUT: int = 30  # таймаут переключения процесса (секунды)
    PROCESS_STARTUP_WAIT: int = 10  # время ожидания запуска процесса (секунды)
    PROCESS_RESTORE_ON_RELEASE: bool = True  # восстанавливать процесс после освобождения
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Преобразует строку CORS_ORIGINS в список"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    @property
    def mysql_database_url(self) -> str:
        """Формирует URL для подключения к MySQL"""
        from urllib.parse import quote_plus
        password_encoded = quote_plus(self.DB_PASSWORD)
        return f"mysql+pymysql://{self.DB_USER}:{password_encoded}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"


settings = Settings()

