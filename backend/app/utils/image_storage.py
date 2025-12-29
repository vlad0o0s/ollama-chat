"""
Утилита для сохранения сгенерированных изображений
"""
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional
import logging
from ..config import settings

logger = logging.getLogger(__name__)


class ImageStorage:
    """Класс для управления хранением изображений"""
    
    def __init__(self):
        """Инициализация хранилища"""
        self.base_path = Path(settings.IMAGE_STORAGE_PATH)
        self._ensure_base_directory()
    
    def _ensure_base_directory(self):
        """Создает базовую директорию, если её нет"""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Директория для изображений: {self.base_path.absolute()}")
        except Exception as e:
            logger.error(f"❌ Ошибка создания директории для изображений: {e}")
            raise
    
    def _get_date_path(self) -> Path:
        """
        Возвращает путь для текущей даты (YYYY/MM/DD)
        
        Returns:
            Path объект для директории текущей даты
        """
        now = datetime.now()
        date_path = self.base_path / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"
        date_path.mkdir(parents=True, exist_ok=True)
        return date_path
    
    def _generate_filename(self, original_filename: Optional[str] = None) -> str:
        """
        Генерирует уникальное имя файла
        
        Args:
            original_filename: Оригинальное имя файла (опционально)
            
        Returns:
            Уникальное имя файла с расширением
        """
        if original_filename:
            # Извлекаем расширение из оригинального имени
            ext = Path(original_filename).suffix or ".png"
        else:
            ext = ".png"
        
        # Генерируем UUID и добавляем timestamp для уникальности
        unique_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{timestamp}_{unique_id[:8]}{ext}"
    
    def save_image(self, image_bytes: bytes, original_filename: Optional[str] = None) -> Tuple[str, str]:
        """
        Сохраняет изображение в хранилище
        
        Args:
            image_bytes: Изображение в виде bytes
            original_filename: Оригинальное имя файла (опционально)
            
        Returns:
            Кортеж (относительный URL, абсолютный путь к файлу)
        """
        try:
            # Получаем путь для текущей даты
            date_path = self._get_date_path()
            
            # Генерируем уникальное имя файла
            filename = self._generate_filename(original_filename)
            
            # Полный путь к файлу
            file_path = date_path / filename
            
            # Сохраняем изображение
            with open(file_path, "wb") as f:
                f.write(image_bytes)
            
            # Формируем относительный URL
            # Относительно базовой директории static/images
            # date_path уже находится внутри base_path, поэтому используем relative_to
            try:
                relative_path = date_path.relative_to(self.base_path)
                relative_url = f"/static/images/{relative_path}/{filename}"
            except ValueError:
                # Если не получается вычислить относительный путь, используем полный путь от base_path
                relative_url = f"/static/images/{date_path.name}/{filename}"
            
            logger.info(f"✅ Изображение сохранено: {file_path}")
            logger.debug(f"   URL: {relative_url}")
            
            return (relative_url, str(file_path.absolute()))
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения изображения: {e}")
            raise
    
    def get_image_path(self, relative_url: str) -> Optional[Path]:
        """
        Получает путь к файлу по относительному URL
        
        Args:
            relative_url: Относительный URL изображения
            
        Returns:
            Path к файлу или None, если файл не найден
        """
        try:
            # Убираем /static/images/ из начала URL
            if relative_url.startswith("/static/images/"):
                relative_path = relative_url[len("/static/images/"):]
            elif relative_url.startswith("static/images/"):
                relative_path = relative_url[len("static/images/"):]
            else:
                relative_path = relative_url
            
            file_path = self.base_path / relative_path
            
            if file_path.exists():
                return file_path
            else:
                logger.warning(f"⚠️ Файл не найден: {file_path}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения пути к изображению: {e}")
            return None
    
    def delete_image(self, relative_url: str) -> bool:
        """
        Удаляет изображение из хранилища
        
        Args:
            relative_url: Относительный URL изображения
            
        Returns:
            True, если файл удален, False в противном случае
        """
        try:
            file_path = self.get_image_path(relative_url)
            if file_path and file_path.exists():
                file_path.unlink()
                logger.info(f"✅ Изображение удалено: {file_path}")
                return True
            else:
                logger.warning(f"⚠️ Файл для удаления не найден: {relative_url}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка удаления изображения: {e}")
            return False


# Глобальный экземпляр хранилища
image_storage = ImageStorage()

