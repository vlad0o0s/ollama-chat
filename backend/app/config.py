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
    OLLAMA_VISION_MODEL: str = "llava:13b"  # Модель для визуального анализа изображений
    OLLAMA_VISION_TIMEOUT: int = 30  # таймаут для визуального анализа (секунды)
    
    # ComfyUI Configuration
    COMFYUI_URL: str = ""  # URL ComfyUI сервера (если пусто и используется Process Manager, будет использован http://127.0.0.1:8188)
    COMFYUI_MODEL: str = "flux1-dev-fp8"
    COMFYUI_TIMEOUT: int = 300  # секунд (5 минут)
    COMFYUI_RETRY_ATTEMPTS: int = 3
    COMFYUI_WORKFLOW_PATH: str = r"C:\ComfyUI_windows_portable\ComfyUI\Flux.json"  # Путь к JSON workflow шаблону
    COMFYUI_WORKFLOW_IMG2IMG_PATH: str = r"C:\ComfyUI_windows_portable\ComfyUI\Flux-img-to-img.json"  # Путь к JSON workflow шаблону для img-to-img
    
    # Image Storage Configuration
    IMAGE_STORAGE_PATH: str = "static/images"
    IMAGE_DEFAULT_WIDTH: int = 1024
    IMAGE_DEFAULT_HEIGHT: int = 1024
    IMAGE_MAX_WIDTH_UPLOAD: int = 4096  # Максимальная ширина изображения при загрузке
    IMAGE_MAX_HEIGHT_UPLOAD: int = 4096  # Максимальная высота изображения при загрузке
    IMAGE_MAX_SIZE_FOR_GENERATION: int = 1024  # Максимальный размер (по большей стороне) для генерации, изображения больше будут сжаты
    IMAGE_MIN_WIDTH: int = 64  # Минимальная ширина изображения
    IMAGE_MIN_HEIGHT: int = 64  # Минимальная высота изображения
    
    # GPU Resource Management
    GPU_MONITOR_ENABLED: bool = True
    GPU_MONITOR_INTERVAL: int = 2  # секунды между проверками
    GPU_VRAM_THRESHOLD: int = 90  # процент использования VRAM для блокировки
    GPU_MIN_FREE_VRAM_MB: int = 1024  # минимум свободной VRAM для новых задач (уменьшено, так как процессы переключаются)
    GPU_WAIT_TIMEOUT: int = 300  # таймаут ожидания GPU (секунды)
    GPU_PRIORITY_COMFYUI: int = 10  # приоритет ComfyUI (высший)
    GPU_PRIORITY_OLLAMA: int = 5  # приоритет Ollama (средний)
    GPU_SERVICE_AVAILABILITY_TIMEOUT: int = 60  # таймаут ожидания доступности сервиса (секунды)
    GPU_ALWAYS_RESTORE_OLLAMA_AFTER_COMFYUI: bool = True  # всегда восстанавливать Ollama после ComfyUI
    
    # Process Management API
    PROCESS_MANAGER_API_URL: str = "http://localhost:8888"  # URL Process Management API (локальный сервер)
    PROCESS_SWITCH_TIMEOUT: int = 30  # таймаут переключения процесса (секунды)
    PROCESS_STARTUP_WAIT: int = 10  # время ожидания запуска процесса (секунды)
    PROCESS_RESTORE_ON_RELEASE: bool = True  # восстанавливать процесс после освобождения
    
    # ComfyUI Configuration
    COMFYUI_URL: str = ""  # URL ComfyUI сервера (обязательно указать в .env)
    COMFYUI_MODEL: str = "flux1-dev-fp8"
    COMFYUI_TIMEOUT: int = 300  # секунд (5 минут)
    COMFYUI_RETRY_ATTEMPTS: int = 3
    
    # Image Storage Configuration
    IMAGE_STORAGE_PATH: str = "static/images"
    IMAGE_DEFAULT_WIDTH: int = 1024
    IMAGE_DEFAULT_HEIGHT: int = 1024
    
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

