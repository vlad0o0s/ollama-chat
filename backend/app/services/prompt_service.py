"""
Сервис для перевода и улучшения промптов для генерации изображений
"""
import httpx
import json
import logging
import re
from typing import Dict, Optional
from ..config import settings
from .resource_manager import resource_manager
from .service_types import ServiceType

logger = logging.getLogger(__name__)


class PromptService:
    """Сервис для работы с промптами через Ollama"""
    
    def __init__(self):
        """Инициализация сервиса"""
        self.ollama_url = settings.OLLAMA_URL
        self.model = settings.OLLAMA_DEFAULT_MODEL
        
    async def translate_and_enhance_prompt(self, russian_description: str, user_id: Optional[int] = None) -> Dict:
        """
        Переводит русское описание в качественный английский промпт и создает негативный промпт
        
        Args:
            russian_description: Описание изображения на русском языке
            user_id: ID пользователя (для приоритизации)
            
        Returns:
            Словарь с промптами:
            {
                "positive": str,  # Положительный промпт на английском
                "negative": str,  # Негативный промпт на английском
                "success": bool,
                "error": Optional[str]
            }
        """
        system_prompt = """You are a professional prompt engineer for AI image generation using Flux model.
Your task is to translate the user's Russian description into a high-quality, detailed English prompt.

Requirements for the positive prompt:
- Be detailed and specific
- Include style keywords (photorealistic, cinematic, artistic, etc.)
- Include composition details (close-up, wide shot, portrait, etc.)
- Include lighting details (natural lighting, studio lighting, golden hour, etc.)
- Include quality keywords (high quality, detailed, 8k, etc.)
- Use professional photography and art terminology
- Keep it concise but descriptive (50-150 words)

Requirements for the negative prompt:
- List common unwanted elements (blurry, low quality, distorted, etc.)
- Include specific exclusions based on the description context
- Keep it concise (20-50 words)

Return ONLY valid JSON in this exact format:
{
  "positive": "detailed English prompt here",
  "negative": "unwanted elements here"
}

Do not include any text before or after the JSON. Only return the JSON object."""

        user_message = f"Переведи это описание изображения в качественный промпт для Flux модели:\n\n{russian_description}"
        
        # Оцениваем требуемую VRAM для Ollama (обычно 2-4GB)
        # Уменьшаем требования, так как процесс будет переключен перед использованием
        estimated_vram_mb = 2048  # 2GB - после переключения процессов VRAM будет свободна
        
        # Получаем блокировку GPU через Resource Manager
        try:
            async with await resource_manager.acquire_gpu(
                service_type=ServiceType.OLLAMA,
                user_id=user_id,
                required_vram_mb=estimated_vram_mb,
                timeout=60
            ) as gpu_lock:
                logger.info(f"🔒 GPU заблокирован для Ollama (перевод промпта, ID: {gpu_lock.lock_id[:8]})")
                
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        payload = {
                            "model": self.model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": system_prompt
                                },
                                {
                                    "role": "user",
                                    "content": user_message
                                }
                            ],
                            "stream": False,
                            "format": "json"  # Запрашиваем JSON формат, если модель поддерживает
                        }
                        
                        response = await client.post(
                            f"{self.ollama_url}/api/chat",
                            json=payload
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            content = result.get("message", {}).get("content", "")
                            
                            # Пытаемся распарсить JSON из ответа
                            try:
                                # Убираем markdown code blocks, если есть
                                content = content.strip()
                                if content.startswith("```"):
                                    # Удаляем ```json и ``` в начале и конце
                                    lines = content.split("\n")
                                    if lines[0].startswith("```"):
                                        lines = lines[1:]
                                    if lines[-1].strip() == "```":
                                        lines = lines[:-1]
                                    content = "\n".join(lines)
                                
                                prompt_data = json.loads(content)
                                
                                positive = prompt_data.get("positive", "")
                                negative = prompt_data.get("negative", "")
                                
                                if not positive:
                                    raise ValueError("Положительный промпт пустой")
                                
                                # Если негативный промпт пустой, используем стандартный
                                if not negative:
                                    negative = "blurry, low quality, distorted, ugly, bad anatomy, bad proportions, watermark, signature, text, error, jpeg artifacts, worst quality, low quality, normal quality, username, artist name"
                                
                                logger.info(f"✅ Промпты успешно сгенерированы")
                                return {
                                    "positive": positive.strip(),
                                    "negative": negative.strip(),
                                    "success": True,
                                    "error": None
                                }
                                
                            except json.JSONDecodeError as e:
                                logger.error(f"❌ Ошибка парсинга JSON от Ollama: {e}")
                                logger.debug(f"Ответ от Ollama: {content[:500]}")
                                
                                # Fallback: пытаемся извлечь промпты из текста
                                return self._fallback_prompt_extraction(content, russian_description)
                                
                        else:
                            error_msg = f"Ошибка Ollama API: {response.status_code} - {response.text}"
                            logger.error(f"❌ {error_msg}")
                            return {
                                "positive": "",
                                "negative": "",
                                "success": False,
                                "error": error_msg
                            }
                            
                except httpx.TimeoutException:
                    logger.error("❌ Таймаут при запросе к Ollama")
                    return {
                        "positive": "",
                        "negative": "",
                        "success": False,
                        "error": "Таймаут при запросе к Ollama"
                    }
                except Exception as e:
                    logger.error(f"❌ Ошибка при генерации промптов: {e}")
                    return {
                        "positive": "",
                        "negative": "",
                        "success": False,
                        "error": str(e)
                    }
                    
        except TimeoutError as e:
            logger.error(f"❌ Таймаут ожидания GPU для Ollama (перевод промпта): {e}")
            return {
                "positive": "",
                "negative": "",
                "success": False,
                "error": f"Таймаут ожидания GPU: {str(e)}"
            }
        except Exception as e:
            logger.error(f"❌ Ошибка при работе с Resource Manager: {e}")
            return {
                "positive": "",
                "negative": "",
                "success": False,
                "error": f"Ошибка управления ресурсами: {str(e)}"
            }
    
    def _fallback_prompt_extraction(self, content: str, original_description: str) -> Dict:
        """
        Fallback метод для извлечения промптов, если JSON парсинг не удался
        
        Args:
            content: Ответ от Ollama
            original_description: Исходное описание на русском
            
        Returns:
            Словарь с промптами
        """
        # Простая эвристика: ищем "positive" и "negative" в тексте
        positive = ""
        negative = ""
        
        # Пытаемся найти JSON-подобные структуры
        # Ищем "positive": "..."
        positive_match = re.search(r'"positive"\s*:\s*"([^"]+)"', content, re.IGNORECASE)
        if positive_match:
            positive = positive_match.group(1)
        
        # Ищем "negative": "..."
        negative_match = re.search(r'"negative"\s*:\s*"([^"]+)"', content, re.IGNORECASE)
        if negative_match:
            negative = negative_match.group(1)
        
        # Если не нашли, используем простой перевод
        if not positive:
            # Простой fallback: используем исходное описание как есть
            # (в реальности можно добавить простой переводчик)
            positive = original_description
            logger.warning("⚠️ Использован fallback: исходное описание без перевода")
        
        if not negative:
            negative = "blurry, low quality, distorted, ugly, bad anatomy, bad proportions, watermark, signature, text, error, jpeg artifacts, worst quality, low quality"
        
        return {
            "positive": positive.strip(),
            "negative": negative.strip(),
            "success": True,
            "error": "Использован fallback метод (JSON парсинг не удался)"
        }


# Глобальный экземпляр сервиса
prompt_service = PromptService()
