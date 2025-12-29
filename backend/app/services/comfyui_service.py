"""
Сервис для работы с ComfyUI API для генерации изображений
"""
import httpx
import json
import asyncio
import logging
from typing import Dict, Optional, Tuple
from ..config import settings

logger = logging.getLogger(__name__)


class ComfyUIService:
    """Сервис для генерации изображений через ComfyUI API"""
    
    def __init__(self):
        """Инициализация сервиса ComfyUI"""
        self.base_url = self._detect_comfyui_url()
        self.model = settings.COMFYUI_MODEL
        self.timeout = settings.COMFYUI_TIMEOUT
        self.retry_attempts = settings.COMFYUI_RETRY_ATTEMPTS
        
    def _detect_comfyui_url(self) -> str:
        """
        Определяет доступный URL ComfyUI из настроек
        """
        # Используем URL из настроек
        comfyui_url = settings.COMFYUI_URL
        
        if not comfyui_url:
            logger.error("❌ COMFYUI_URL не установлен в настройках")
            raise ValueError("COMFYUI_URL должен быть установлен в .env файле")
        
        # Проверяем доступность (синхронно, так как это инициализация)
        try:
            import httpx
            try:
                with httpx.Client(timeout=2.0) as client:
                    response = client.get(f"{comfyui_url}/system_stats")
                    if response.status_code == 200:
                        logger.info(f"✅ ComfyUI обнаружен на {comfyui_url}")
                        return comfyui_url
                    else:
                        logger.warning(f"⚠️ ComfyUI недоступен на {comfyui_url} (статус: {response.status_code})")
            except Exception as e:
                logger.warning(f"⚠️ ComfyUI недоступен на {comfyui_url}: {e}")
                logger.info(f"ℹ️ Используется URL из настроек: {comfyui_url}")
        except ImportError:
            logger.warning("⚠️ httpx не установлен, пропускаем проверку доступности ComfyUI")
        
        # Возвращаем URL из настроек даже если проверка не удалась
        return comfyui_url
    
    async def check_connection(self) -> bool:
        """Проверяет доступность ComfyUI сервера"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка подключения к ComfyUI: {e}")
            return False
    
    def create_workflow(self, prompt: str, negative_prompt: str, width: int = 1024, height: int = 1024) -> Dict:
        """
        Создает workflow JSON для ComfyUI с моделью flux1-dev-fp8
        
        Args:
            prompt: Положительный промпт на английском
            negative_prompt: Негативный промпт на английском
            width: Ширина изображения (по умолчанию 1024)
            height: Высота изображения (по умолчанию 1024)
            
        Returns:
            Словарь с workflow для ComfyUI
        """
        # Генерируем уникальные ID для нод
        import uuid
        
        # Создаем базовые ID для нод
        checkpoint_loader = str(uuid.uuid4())
        clip_text_encode_pos = str(uuid.uuid4())
        clip_text_encode_neg = str(uuid.uuid4())
        empty_latent = str(uuid.uuid4())
        ksampler = str(uuid.uuid4())
        vae_decode = str(uuid.uuid4())
        save_image = str(uuid.uuid4())
        
        workflow = {
            checkpoint_loader: {
                "inputs": {
                    "ckpt_name": f"{self.model}.safetensors"
                },
                "class_type": "CheckpointLoaderSimple"
            },
            clip_text_encode_pos: {
                "inputs": {
                    "text": prompt,
                    "clip": [checkpoint_loader, 1]
                },
                "class_type": "CLIPTextEncode"
            },
            clip_text_encode_neg: {
                "inputs": {
                    "text": negative_prompt,
                    "clip": [checkpoint_loader, 1]
                },
                "class_type": "CLIPTextEncode"
            },
            empty_latent: {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            ksampler: {
                "inputs": {
                    "seed": 0,  # 0 = случайный seed (ComfyUI не принимает -1)
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": [checkpoint_loader, 0],
                    "positive": [clip_text_encode_pos, 0],
                    "negative": [clip_text_encode_neg, 0],
                    "latent_image": [empty_latent, 0]
                },
                "class_type": "KSampler"
            },
            vae_decode: {
                "inputs": {
                    "samples": [ksampler, 0],
                    "vae": [checkpoint_loader, 2]
                },
                "class_type": "VAEDecode"
            },
            save_image: {
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": [vae_decode, 0]
                },
                "class_type": "SaveImage"
            }
        }
        
        return workflow
    
    async def queue_prompt(self, workflow: Dict) -> Optional[str]:
        """
        Добавляет workflow в очередь ComfyUI
        
        Args:
            workflow: Workflow JSON для генерации
            
        Returns:
            prompt_id или None в случае ошибки
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {"prompt": workflow}
                response = await client.post(
                    f"{self.base_url}/prompt",
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    prompt_id = result.get("prompt_id")
                    if prompt_id:
                        logger.info(f"✅ Workflow добавлен в очередь, prompt_id: {prompt_id}")
                        return prompt_id
                    else:
                        logger.error(f"❌ Не получен prompt_id из ответа: {result}")
                        return None
                else:
                    logger.error(f"❌ Ошибка при добавлении в очередь: {response.status_code} - {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error("❌ Таймаут при добавлении workflow в очередь")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при добавлении workflow в очередь: {e}")
            return None
    
    async def get_image(self, prompt_id: str) -> Optional[Tuple[bytes, str]]:
        """
        Получает готовое изображение по prompt_id
        
        Args:
            prompt_id: ID промпта из очереди
            
        Returns:
            Кортеж (изображение в bytes, имя файла) или None
        """
        max_wait_time = self.timeout
        check_interval = 2  # Проверяем каждые 2 секунды
        elapsed_time = 0
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while elapsed_time < max_wait_time:
                    # Проверяем историю
                    response = await client.get(f"{self.base_url}/history/{prompt_id}")
                    
                    if response.status_code == 200:
                        history = response.json()
                        
                        # Ищем завершенные задачи
                        if prompt_id in history:
                            outputs = history[prompt_id].get("outputs", {})
                            
                            # Ищем ноду SaveImage
                            for node_id, node_output in outputs.items():
                                if "images" in node_output:
                                    images = node_output["images"]
                                    if images:
                                        image_info = images[0]
                                        filename = image_info.get("filename", "")
                                        subfolder = image_info.get("subfolder", "")
                                        
                                        # Получаем изображение
                                        image_url = f"{self.base_url}/view"
                                        params = {
                                            "filename": filename,
                                            "subfolder": subfolder,
                                            "type": "output"
                                        }
                                        
                                        image_response = await client.get(image_url, params=params)
                                        
                                        if image_response.status_code == 200:
                                            logger.info(f"✅ Изображение получено: {filename}")
                                            return (image_response.content, filename)
                    
                    # Если не готово, ждем и проверяем снова
                    await asyncio.sleep(check_interval)
                    elapsed_time += check_interval
                    
                    if elapsed_time % 10 == 0:
                        logger.info(f"⏳ Ожидание генерации изображения... ({elapsed_time}s/{max_wait_time}s)")
                
                logger.error(f"❌ Таймаут ожидания изображения (>{max_wait_time}s)")
                return None
                
        except httpx.TimeoutException:
            logger.error("❌ Таймаут при получении изображения")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при получении изображения: {e}")
            return None
    
    async def generate_image(
        self, 
        prompt: str, 
        negative_prompt: str, 
        width: int = 1024, 
        height: int = 1024
    ) -> Dict:
        """
        Полный цикл генерации изображения
        
        Args:
            prompt: Положительный промпт
            negative_prompt: Негативный промпт
            width: Ширина изображения
            height: Высота изображения
            
        Returns:
            Словарь с результатом:
            {
                "success": bool,
                "image": Optional[bytes],
                "filename": Optional[str],
                "prompt_id": Optional[str],
                "error": Optional[str]
            }
        """
        # Проверяем подключение
        if not await self.check_connection():
            return {
                "success": False,
                "image": None,
                "filename": None,
                "prompt_id": None,
                "error": "ComfyUI сервер недоступен"
            }
        
        # Создаем workflow
        workflow = self.create_workflow(prompt, negative_prompt, width, height)
        
        # Добавляем в очередь
        prompt_id = await self.queue_prompt(workflow)
        if not prompt_id:
            return {
                "success": False,
                "image": None,
                "filename": None,
                "prompt_id": None,
                "error": "Не удалось добавить workflow в очередь"
            }
        
        # Получаем изображение
        result = await self.get_image(prompt_id)
        
        if result:
            image_bytes, filename = result
            return {
                "success": True,
                "image": image_bytes,
                "filename": filename,
                "prompt_id": prompt_id,
                "error": None
            }
        else:
            return {
                "success": False,
                "image": None,
                "filename": None,
                "prompt_id": prompt_id,
                "error": "Таймаут ожидания генерации изображения"
            }


# Глобальный экземпляр сервиса
comfyui_service = ComfyUIService()

