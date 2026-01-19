"""
Сервис для перевода и улучшения промптов для генерации изображений
"""
import httpx
import json
import logging
import re
import base64
import asyncio
import time
from typing import Dict, Optional
from ..config import settings
from .resource_manager import resource_manager
from .service_types import ServiceType
from .process_manager_service import process_manager_service

logger = logging.getLogger(__name__)


class PromptService:
    """Сервис для работы с промптами через Ollama"""
    
    def __init__(self):
        """Инициализация сервиса"""
        # Если используется Process Manager, Ollama запускается локально на 127.0.0.1:11434
        # Проверяем, используется ли Process Manager (если PROCESS_MANAGER_API_URL установлен)
        if settings.PROCESS_MANAGER_API_URL:
            # Используем localhost для Process Manager
            self.ollama_url = "http://127.0.0.1:11434"
        else:
            # Используем URL из настроек для прямого подключения
            self.ollama_url = settings.OLLAMA_URL
        self.model = settings.OLLAMA_DEFAULT_MODEL
        # Пул соединений для оптимизации (будет использован в будущем)
        self._client_pool = None
    
    async def process_all_ollama_requests(
        self,
        image_bytes: Optional[bytes] = None,
        russian_description: str = "",
        user_id: Optional[int] = None
    ) -> Dict:
        """
        Группирует все запросы к Ollama в одной сессии GPU для оптимизации
        
        Args:
            image_bytes: Изображение для анализа через LLaVA (опционально)
            russian_description: Описание на русском для генерации промптов
            user_id: ID пользователя
            
        Returns:
            Словарь с результатами:
            {
                "image_description": Optional[str],
                "prompt_result": Dict,
                "ksampler_result": Optional[Dict],
                "success": bool,
                "error": Optional[str]
            }
        """
        estimated_vram_mb = 6144  # 6GB для llava:13b (максимум)
        
        try:
            async with await resource_manager.acquire_gpu(
                service_type=ServiceType.OLLAMA,
                user_id=user_id,
                required_vram_mb=estimated_vram_mb,
                timeout=120  # Увеличенный таймаут для всех запросов
            ) as gpu_lock:
                logger.info(f"🔒 GPU заблокирован для Ollama (группированные запросы, ID: {gpu_lock.lock_id[:8]})")
                
                results = {
                    "image_description": None,
                    "prompt_result": None,
                    "ksampler_result": None,
                    "success": True,
                    "error": None
                }
                
                # 1. Анализ изображения через LLaVA (если есть)
                # ПРИМЕЧАНИЕ: Для полной оптимизации нужно добавить поддержку skip_gpu_lock в analyze_image_with_vision
                if image_bytes:
                    logger.info(f"🔄 [Группированные запросы] Анализ изображения через LLaVA...")
                    # ВАЖНО: Этот вызов создаст дополнительную блокировку GPU
                    # Для полной оптимизации нужно модифицировать analyze_image_with_vision
                    vision_result = await self.analyze_image_with_vision(
                        image_bytes,
                        user_id=user_id
                    )
                    
                    if vision_result.get("success") and vision_result.get("description"):
                        results["image_description"] = vision_result.get("description")
                        logger.info(f"✅ [Группированные запросы] Изображение проанализировано через LLaVA")
                    else:
                        results["success"] = False
                        results["error"] = vision_result.get("error", "Ошибка анализа изображения")
                        return results
                
                # 2. Генерация промптов
                logger.info(f"🔄 [Группированные запросы] Перевод описания в промпты...")
                prompt_result = await self.translate_and_enhance_prompt(
                    russian_description,
                    user_id=user_id,
                    image_description=results["image_description"],
                    skip_gpu_lock=True  # Уже заблокировано в этом методе
                )
                
                if not prompt_result.get("success"):
                    results["success"] = False
                    results["error"] = prompt_result.get("error", "Ошибка генерации промптов")
                    return results
                
                results["prompt_result"] = prompt_result
                
                # 3. Анализ настроек KSampler (только для img-to-img)
                # ПРИМЕЧАНИЕ: Для полной оптимизации нужно добавить поддержку skip_gpu_lock в analyze_img2img_settings
                if image_bytes and results["image_description"]:
                    logger.info(f"🔄 [Группированные запросы] Анализ настроек KSampler...")
                    # ВАЖНО: Этот вызов создаст дополнительную блокировку GPU
                    # Для полной оптимизации нужно модифицировать analyze_img2img_settings
                    ksampler_result = await self.analyze_img2img_settings(
                        russian_description,
                        user_id=user_id,
                        image_description=results["image_description"]
                    )
                    results["ksampler_result"] = ksampler_result
                
                logger.info(f"✅ [Группированные запросы] Все запросы к Ollama выполнены в одной сессии GPU")
                return results
                
        except Exception as e:
            logger.error(f"❌ Ошибка при группированных запросах к Ollama: {e}")
            return {
                "image_description": None,
                "prompt_result": None,
                "ksampler_result": None,
                "success": False,
                "error": str(e)
            }
        
    async def translate_and_enhance_prompt(self, russian_description: str, user_id: Optional[int] = None, image_description: Optional[str] = None, skip_gpu_lock: bool = False) -> Dict:
        """
        Переводит русское описание в качественный английский промпт и создает негативный промпт
        
        Args:
            russian_description: Описание изображения на русском языке
            user_id: ID пользователя (для приоритизации)
            image_description: Описание текущего изображения от LLaVA (опционально)
            
        Returns:
            Словарь с промптами:
            {
                "positive": str,  # Положительный промпт на английском
                "negative": str,  # Негативный промпт на английском
                "success": bool,
                "error": Optional[str]
            }
        """
        # Формируем системный промпт с учетом описания изображения
        if image_description:
            system_prompt = f"""You are a professional prompt engineer for AI image generation using Flux model.
The user wants to modify an existing image based on their description.

CURRENT IMAGE DESCRIPTION (from visual analysis):
{image_description}

Your task is to translate the user's Russian description into a high-quality, detailed English prompt that will transform the current image according to the user's request.

IMPORTANT: You know what the current image looks like. The user wants to change it. Generate a prompt that describes the DESIRED RESULT, not the current state.

CRITICAL: If the user mentions COLOR CHANGES (e.g., "сделать белый", "красный", "изменить цвет"), you MUST:
- Explicitly state the NEW color in the prompt multiple times for emphasis
- Use strong color descriptors (e.g., "pure white", "bright red", "vibrant blue")
- Include color in the main subject description
- Add color emphasis phrases like "the entire object is [color]", "completely [color] in color"
- If the current image has a different color, make sure to emphasize the NEW color strongly

Requirements for the positive prompt:
- Be detailed and specific
- For COLOR CHANGES: Emphasize the NEW color multiple times, use strong color words
- Describe the desired transformation based on the current image description
- Include style keywords (photorealistic, cinematic, artistic, etc.)
- Include composition details (close-up, wide shot, portrait, etc.)
- Include lighting details (natural lighting, studio lighting, golden hour, etc.)
- Include quality keywords (high quality, detailed, 8k, etc.)
- Use professional photography and art terminology
- Keep it concise but descriptive (50-150 words)

Requirements for the negative prompt:
- List common unwanted elements (blurry, low quality, distorted, etc.)
- If color change is requested, explicitly exclude the OLD color from the current image (e.g., if changing from black to white, exclude "black", "dark", "metallic black")
- Include specific exclusions based on the description context
- Keep it concise (20-50 words)

Return ONLY valid JSON in this exact format:
{{
  "positive": "detailed English prompt here",
  "negative": "unwanted elements here"
}}

Do not include any text before or after the JSON. Only return the JSON object."""
        else:
            system_prompt = """You are a professional prompt engineer for AI image generation using Flux model.
Your task is to translate the user's Russian description into a high-quality, detailed English prompt.

CRITICAL: If the user mentions COLOR CHANGES (e.g., "сделать белый", "красный", "изменить цвет"), you MUST:
- Explicitly state the color in the prompt multiple times for emphasis
- Use strong color descriptors (e.g., "pure white", "bright red", "vibrant blue")
- Include color in the main subject description
- Add color emphasis phrases like "the entire object is [color]", "completely [color] in color"

Requirements for the positive prompt:
- Be detailed and specific
- For COLOR CHANGES: Emphasize the color multiple times, use strong color words
- Include style keywords (photorealistic, cinematic, artistic, etc.)
- Include composition details (close-up, wide shot, portrait, etc.)
- Include lighting details (natural lighting, studio lighting, golden hour, etc.)
- Include quality keywords (high quality, detailed, 8k, etc.)
- Use professional photography and art terminology
- Keep it concise but descriptive (50-150 words)

Requirements for the negative prompt:
- List common unwanted elements (blurry, low quality, distorted, etc.)
- If color change is requested, explicitly exclude the OLD color (e.g., if changing to white, exclude "brown", "gray", "metallic")
- Include specific exclusions based on the description context
- Keep it concise (20-50 words)

Return ONLY valid JSON in this exact format:
{
  "positive": "detailed English prompt here",
  "negative": "unwanted elements here"
}

Do not include any text before or after the JSON. Only return the JSON object."""
        
        # Если skip_gpu_lock=True, значит GPU уже заблокирован (группированные запросы)
        if skip_gpu_lock:
            # Выполняем запрос без дополнительной блокировки GPU
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    return await self._execute_prompt_translation(client, russian_description, image_description)
            except Exception as e:
                logger.error(f"❌ Ошибка при генерации промптов (без блокировки GPU): {e}")
                return {
                    "positive": "",
                    "negative": "",
                    "success": False,
                    "error": str(e)
                }
        
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
                        return await self._execute_prompt_translation(client, russian_description, image_description)
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
    
    async def _execute_prompt_translation(self, client: httpx.AsyncClient, russian_description: str, image_description: Optional[str] = None) -> Dict:
        """
        Выполняет перевод промпта (вспомогательный метод для использования с/без блокировки GPU)
        Flux.1-dev требует Natural Language промпты
        """
        # Формируем системный промпт с учетом описания изображения
        # Flux.1-dev требует Natural Language промпты, а не tag-based
        if image_description:
            system_prompt = f"""You are an expert prompt engineer for the Flux.1 image generation model. Your goal is to create a single, cohesive descriptive paragraph in English based on the provided image analysis and the user's modification request.

CURRENT IMAGE DESCRIPTION (from LLaVA visual analysis):
{image_description}

CRITICAL INSTRUCTIONS:

1. Use Natural Language: Do NOT use tags, commas, or "keyword soup" (e.g., "black cat, 8k, sharp"). Write in full, descriptive sentences that flow naturally.

2. Prioritize User Requests: If the user asks for a "black cat" but LLaVA describes a "brown cat," the final prompt MUST describe a black cat. The user's request takes priority over the current image description.

3. Focus on Details: Describe lighting (e.g., "warm indoor glow"), textures (e.g., "glossy fur," "pine needles"), and interactions between objects.

4. Avoid Junk Words: Do NOT use "photorealistic," "ultra-detailed," "8k," "masterpiece," or similar quality tags. Flux does not need them and they can degrade results.

5. No Negative Prompting: Do NOT generate a negative prompt. Flux handles quality through the main description. Return an empty string for negative.

6. Output Format: Provide ONLY valid JSON with the final prompt text. No introduction or explanation.

Example:
Input - LLaVA: "A brown tabby cat reaching for gold ornaments on a green tree."
User: "Make it a black cat and use red ornaments."
Output: {{"positive": "A high-quality photo of a sleek black cat perched within the branches of a lush Christmas tree. The cat is playfully swatting at vibrant red spheres. Soft, golden holiday lights twinkle in the background, casting a gentle sheen on the cat's dark fur and the sharp green pine needles.", "negative": ""}}

Return ONLY valid JSON in this exact format:
{{
  "positive": "single cohesive descriptive paragraph in natural English",
  "negative": ""
}}

Do not include any text before or after the JSON. Only return the JSON object."""
        else:
            system_prompt = """You are an expert prompt engineer for the Flux.1 image generation model. Your goal is to create a single, cohesive descriptive paragraph in English based on the user's request.

CRITICAL INSTRUCTIONS:

1. Use Natural Language: Do NOT use tags, commas, or "keyword soup" (e.g., "black cat, 8k, sharp"). Write in full, descriptive sentences that flow naturally.

2. Focus on Details: Describe lighting (e.g., "warm indoor glow"), textures (e.g., "glossy fur," "pine needles"), and interactions between objects.

3. Avoid Junk Words: Do NOT use "photorealistic," "ultra-detailed," "8k," "masterpiece," or similar quality tags. Flux does not need them and they can degrade results.

4. No Negative Prompting: Do NOT generate a negative prompt. Flux handles quality through the main description. Return an empty string for negative.

5. Output Format: Provide ONLY valid JSON with the final prompt text. No introduction or explanation.

Return ONLY valid JSON in this exact format:
{
  "positive": "single cohesive descriptive paragraph in natural English",
  "negative": ""
}

Do not include any text before or after the JSON. Only return the JSON object."""

        if image_description:
            user_message = f"LLaVA analysis: {image_description}\n\nUser request: {russian_description}\n\nGenerate a natural language prompt for Flux.1 that transforms the image according to the user's request."
        else:
            user_message = f"User request: {russian_description}\n\nGenerate a natural language prompt for Flux.1 based on this description."
        
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
                
                # Для Flux.1-dev negative prompt должен быть пустым
                # Flux не использует negative prompting, качество контролируется через основной промпт
                negative = ""  # Всегда пустой для Flux.1-dev
                
                # НЕ используем _enhance_color_change_prompts для Flux.1-dev
                # Промпт должен быть естественным языком, а не tag-based
                
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
        
        # Для Flux.1-dev negative prompt должен быть пустым
        negative = ""  # Всегда пустой для Flux.1-dev
        
        # НЕ используем _enhance_color_change_prompts для Flux.1-dev
        # Промпт должен быть естественным языком
        
        return {
            "positive": positive.strip(),
            "negative": "",  # Всегда пустой для Flux.1-dev
            "success": True,
            "error": "Использован fallback метод (JSON парсинг не удался)"
        }
    
    def _enhance_color_change_prompts(self, positive: str, negative: str, russian_description: str) -> tuple:
        """
        Усиливает промпты для изменения цвета, если обнаружено упоминание цвета в описании
        
        Args:
            positive: Положительный промпт
            negative: Негативный промпт
            russian_description: Исходное описание на русском
            
        Returns:
            Кортеж (enhanced_positive, enhanced_negative)
        """
        description_lower = russian_description.lower()
        
        # Словарь цветов: русский -> английский
        color_map = {
            "белый": "white",
            "красный": "red",
            "синий": "blue",
            "черный": "black",
            "зеленый": "green",
            "желтый": "yellow",
            "оранжевый": "orange",
            "фиолетовый": "purple",
            "розовый": "pink",
            "коричневый": "brown",
            "серый": "gray",
            "голубой": "light blue",
            "бежевый": "beige",
            "золотой": "golden",
            "серебряный": "silver"
        }
        
        # Проверяем, есть ли упоминание цвета
        detected_colors = []
        for ru_color, en_color in color_map.items():
            if ru_color in description_lower:
                detected_colors.append((ru_color, en_color))
        
        # Если обнаружено изменение цвета, усиливаем промпт
        if detected_colors:
            logger.info(f"🎨 Обнаружено изменение цвета: {[c[1] for c in detected_colors]}")
            
            for ru_color, en_color in detected_colors:
                # Усиливаем положительный промпт
                color_phrases = [
                    f"completely {en_color} in color",
                    f"entirely {en_color}",
                    f"pure {en_color}",
                    f"fully {en_color}",
                    f"the entire object is {en_color}"
                ]
                
                # Добавляем усиление цвета, если его еще нет в промпте
                en_color_lower = en_color.lower()
                if en_color_lower not in positive.lower():
                    # Добавляем цвет в начало промпта для акцента
                    positive = f"{en_color.capitalize()} color, " + positive
                
                # Добавляем дополнительные фразы для усиления
                for phrase in color_phrases[:2]:  # Берем первые 2 фразы
                    if phrase.lower() not in positive.lower():
                        positive += f", {phrase}"
                
                # Усиливаем негативный промпт - исключаем другие цвета
                other_colors = [c[1] for c in detected_colors if c[1] != en_color]
                for other_color in other_colors:
                    if other_color.lower() not in negative.lower():
                        negative += f", {other_color}"
                
                # Исключаем общие цвета, которые могут мешать
                conflicting_colors = ["brown", "gray", "metallic", "silver", "gold"]
                if en_color.lower() not in [c.lower() for c in conflicting_colors]:
                    for conf_color in conflicting_colors:
                        if conf_color.lower() not in negative.lower():
                            negative += f", {conf_color}"
        
        return positive, negative
    
    def _validate_image_description(self, description: str) -> Dict[str, any]:
        """
        Проверяет полноту описания изображения
        
        Args:
            description: Описание изображения от LLaVA
            
        Returns:
            Словарь с результатом проверки:
            {
                "complete": bool,
                "missing_categories": List[str],
                "has_colors": bool,
                "has_materials": bool,
                "has_objects": bool
            }
        """
        description_lower = description.lower()
        
        # Ключевые слова для проверки наличия категорий
        color_keywords = ["color", "colour", "red", "blue", "green", "yellow", "white", "black", "brown", "gray", "grey", "pink", "orange", "purple", "shade", "tone", "bright", "dark", "light"]
        material_keywords = ["wood", "metal", "plastic", "fabric", "stone", "glass", "concrete", "texture", "smooth", "rough", "glossy", "matte", "reflective", "porous"]
        object_keywords = ["object", "item", "thing", "fence", "wall", "building", "tree", "car", "person", "animal", "structure"]
        
        has_colors = any(keyword in description_lower for keyword in color_keywords)
        has_materials = any(keyword in description_lower for keyword in material_keywords)
        has_objects = any(keyword in description_lower for keyword in object_keywords)
        
        missing_categories = []
        if not has_colors:
            missing_categories.append("colors")
        if not has_materials:
            missing_categories.append("materials")
        if not has_objects:
            missing_categories.append("objects")
        
        complete = len(missing_categories) == 0
        
        return {
            "complete": complete,
            "missing_categories": missing_categories,
            "has_colors": has_colors,
            "has_materials": has_materials,
            "has_objects": has_objects
        }
    
    async def analyze_image_with_vision(self, image_bytes: bytes, user_id: Optional[int] = None) -> Dict:
        """
        Анализирует изображение через LLaVA и возвращает детальное описание
        
        Args:
            image_bytes: Изображение в виде bytes
            user_id: ID пользователя (для приоритизации)
            
        Returns:
            Словарь с результатом:
            {
                "description": str,  # Описание изображения на русском языке
                "success": bool,
                "error": Optional[str]
            }
        """
        try:
            # Сжимаем изображение перед отправкой в LLaVA, чтобы уменьшить размер запроса
            # Это предотвращает падение Ollama из-за слишком больших запросов
            from PIL import Image
            from io import BytesIO
            
            # Определяем формат изображения по magic bytes (до сжатия)
            image_format = "png"
            if image_bytes.startswith(b'\xff\xd8\xff'):
                image_format = "jpeg"
            elif image_bytes.startswith(b'\x89PNG'):
                image_format = "png"
            elif image_bytes.startswith(b'RIFF') and b'WEBP' in image_bytes[:12]:
                image_format = "webp"
            
            try:
                image = Image.open(BytesIO(image_bytes))
                original_width, original_height = image.size
                
                # Максимальный размер для LLaVA (уменьшаем до 768px для экономии памяти)
                max_size_for_llava = 768
                max_dimension = max(original_width, original_height)
                
                if max_dimension > max_size_for_llava:
                    # Вычисляем новые размеры с сохранением пропорций
                    if original_width > original_height:
                        new_width = max_size_for_llava
                        new_height = int(original_height * (max_size_for_llava / original_width))
                    else:
                        new_height = max_size_for_llava
                        new_width = int(original_width * (max_size_for_llava / original_height))
                    
                    # Сжимаем изображение
                    resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Сохраняем в bytes с оптимизацией
                    output = BytesIO()
                    # Используем JPEG для лучшего сжатия (если исходное изображение не требует прозрачности)
                    has_transparency = image.mode in ('RGBA', 'LA') or (hasattr(image, 'info') and 'transparency' in image.info)
                    if not has_transparency:
                        resized_image = resized_image.convert('RGB')
                        resized_image.save(output, format='JPEG', quality=85, optimize=True)
                        image_format = "jpeg"
                    else:
                        resized_image.save(output, format='PNG', optimize=True)
                        image_format = "png"
                    
                    image_bytes = output.getvalue()
                    logger.info(f"✅ Изображение сжато для LLaVA: {original_width}x{original_height} -> {new_width}x{new_height} (размер: {len(image_bytes)} байт)")
                else:
                    logger.debug(f"✅ Изображение {original_width}x{original_height} не требует сжатия для LLaVA")
            except Exception as resize_error:
                logger.warning(f"⚠️ Не удалось сжать изображение для LLaVA: {resize_error}, используем оригинал")
            
            # Конвертируем изображение в base64
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            logger.debug(f"📊 Размер base64 для LLaVA: {len(base64_image)} символов")
            
            # Формируем data URL
            data_url = f"data:image/{image_format};base64,{base64_image}"
            
            system_prompt = """You are an expert image analyzer. Your task is to provide an extremely detailed description of the image in English.

CRITICAL REQUIREMENTS - you MUST describe ALL of the following in detail:

1. COLORS - Describe every color you see:
   - Main colors of all objects
   - Secondary colors and accents
   - Color tones and shades (light, dark, bright, muted)
   - Color distribution across the image
   - Any color gradients or transitions

2. MATERIALS - Identify and describe materials of ALL objects:
   - Surface materials (wood, metal, plastic, fabric, stone, glass, etc.)
   - Material textures (smooth, rough, glossy, matte, reflective, etc.)
   - Material properties (transparent, opaque, shiny, dull, etc.)
   - Material condition (new, old, worn, polished, etc.)

3. OBJECTS - List and describe ALL objects:
   - What objects are in the image
   - Their sizes and proportions
   - Their positions and arrangement
   - Their relationships to each other

4. COMPOSITION:
   - Overall layout and arrangement
   - Foreground, middle ground, background
   - Perspective and angle
   - Focal points

5. LIGHTING:
   - Light sources and direction
   - Shadows and highlights
   - Overall lighting mood (bright, dim, dramatic, etc.)

6. STYLE AND ATMOSPHERE:
   - Overall style (realistic, artistic, etc.)
   - Mood and atmosphere
   - Any special effects or filters

EXAMPLE OF A GOOD DESCRIPTION:
"A wooden fence in the foreground, painted in a dark brown color with a matte finish. The wood grain is visible, showing a rough, weathered texture. The fence consists of vertical wooden planks approximately 2 meters tall, with horizontal support beams. The material appears to be aged wood with some wear and minor cracks. The fence is positioned in the center of the image, extending horizontally across the frame. In the background, there is a green grassy field under a bright blue sky with white clouds. The lighting is natural daylight from above, casting soft shadows on the ground. The overall style is photorealistic with a warm, sunny atmosphere."

Be extremely thorough and specific. Your description will be used to transform this image, so every detail matters. Write in English, be very detailed, and mention EVERYTHING you see. Use professional English terminology for colors, materials, and composition.

After your description, add a brief completeness check:
- [✓] Colors described
- [✓] Materials identified
- [✓] Objects listed
- [✓] Composition noted
- [✓] Lighting described"""
            
            # Для Ollama LLaVA нужно использовать формат с полем "images" для base64 изображения
            user_message_text = """Describe this image in extreme detail in English.

MANDATORY - you MUST describe:
1. ALL colors - every color of every object, shades, brightness, saturation
2. ALL materials - what each object is made of (wood, metal, plastic, fabric, stone, glass, concrete, etc.)
3. Material textures - smooth, rough, glossy, matte, reflective, matte, porous, etc.
4. ALL objects - what is in the image, their sizes, proportions, and positions
5. Composition - how objects are arranged, foreground, middle ground, background, perspective
6. Lighting - light sources, direction, shadows, highlights, overall lighting mood
7. Style and atmosphere - overall style, mood, any special effects

Be extremely detailed and precise. Your description will be used to transform this image, so every detail matters. Use professional English terminology."""
            
            # Оцениваем требуемую VRAM для LLaVA (уменьшено, чтобы не блокировать повторные запросы)
            # 5GB обычно достаточно для llava:13b на 6GB GPU при правильном освобождении VRAM
            estimated_vram_mb = 5120  # 5GB для llava:13b
            
            # Для LLaVA требуется принудительный перезапуск Ollama, чтобы освободить VRAM от gpt-oss
            # Это гарантирует, что llava:13b сможет загрузиться без конфликтов
            logger.info(f"🔄 LLaVA требует принудительный перезапуск Ollama для освобождения VRAM от gpt-oss...")
            
            try:
                # Принудительно перезапускаем Ollama перед запросом GPU для LLaVA
                # Это остановит gpt-oss и освободит VRAM
                api_available = await process_manager_service.check_api_available()
                if api_available:
                    logger.info(f"🛑 Принудительная остановка Ollama перед использованием LLaVA...")
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            # Новый API: /stop/ollama
                            stop_response = await client.post(
                                f"{process_manager_service.api_url}/stop/ollama"
                            )
                            if stop_response.status_code == 404:
                                # Фолбек для старого API
                                stop_response = await client.post(
                                    f"{process_manager_service.api_url}/process/stop",
                                    params={"service": "ollama"}
                                )
                            if stop_response.status_code == 200:
                                logger.info(f"✅ Ollama остановлен, ожидание освобождения VRAM (3 секунды)...")
                                await asyncio.sleep(3)  # Даем время на освобождение VRAM
                            else:
                                logger.warning(f"⚠️ Не удалось остановить Ollama: {stop_response.status_code}")
                    except Exception as stop_error:
                        logger.warning(f"⚠️ Ошибка при остановке Ollama: {stop_error}")
                
                async with await resource_manager.acquire_gpu(
                    service_type=ServiceType.OLLAMA,
                    user_id=user_id,
                    required_vram_mb=estimated_vram_mb,
                    timeout=60
                ) as gpu_lock:
                    logger.info(f"🔒 GPU заблокирован для Ollama (анализ изображения через LLaVA, ID: {gpu_lock.lock_id[:8]})")
                    
                    # Даем небольшое время на инициализацию Ollama после переключения процесса
                    await asyncio.sleep(2)
                    
                    # Retry механизм с экспоненциальной задержкой (3 попытки)
                    max_retries = 3
                    retry_delay = 2  # Начальная задержка в секундах
                    last_error = None
                    
                    # Увеличиваем таймаут для первого запроса, так как модель может загружаться
                    # Первый запрос может занять больше времени из-за загрузки модели в память
                    base_timeout = float(settings.OLLAMA_VISION_TIMEOUT)
                    
                    for attempt in range(max_retries):
                        try:
                            # Для первой попытки увеличиваем таймаут, так как модель может загружаться
                            if attempt == 0:
                                timeout_value = max(base_timeout, 180.0)  # Минимум 180 секунд для первой попытки
                                logger.info(f"🔄 Первая попытка с увеличенным таймаутом {timeout_value}s (модель может загружаться)")
                            else:
                                timeout_value = base_timeout
                            
                            # httpx требует float для таймаута или объект httpx.Timeout
                            async with httpx.AsyncClient(timeout=timeout_value) as client:
                                # Для Ollama LLaVA формат запроса: изображение передается в поле "images" как массив base64 строк
                                payload = {
                                    "model": settings.OLLAMA_VISION_MODEL,
                                    "messages": [
                                        {
                                            "role": "system",
                                            "content": system_prompt
                                        },
                                        {
                                            "role": "user",
                                            "content": user_message_text,
                                            "images": [base64_image]  # Ollama ожидает массив base64 строк в поле "images"
                                        }
                                    ],
                                    "stream": False
                                }
                                
                                logger.info(f"🔄 Отправка запроса к LLaVA (попытка {attempt + 1}/{max_retries}, таймаут: {timeout_value}s, размер изображения: {len(image_bytes)} байт, размер base64: {len(base64_image)} символов)")
                                logger.debug(f"   URL: {self.ollama_url}/api/chat")
                                logger.debug(f"   Модель: {settings.OLLAMA_VISION_MODEL}")
                                request_start_time = time.time()
                                try:
                                    response = await client.post(
                                        f"{self.ollama_url}/api/chat",
                                        json=payload
                                    )
                                    request_time = time.time() - request_start_time
                                    logger.info(f"📊 Ответ от LLaVA получен за {request_time:.2f}s (статус: {response.status_code})")
                                except httpx.TimeoutException as timeout_err:
                                    request_time = time.time() - request_start_time
                                    logger.error(f"❌ Таймаут запроса к LLaVA после {request_time:.2f}s (таймаут был {timeout_value}s)")
                                    raise
                                
                                if response.status_code == 200:
                                    result = response.json()
                                    description = result.get("message", {}).get("content", "")
                                    
                                    if description:
                                        logger.info(f"✅ Изображение проанализировано через LLaVA (длина описания: {len(description)} символов, попытка {attempt + 1}/{max_retries})")
                                        logger.debug(f"   Описание: {description[:200]}...")
                                        
                                        # Проверяем полноту описания
                                        validation = self._validate_image_description(description)
                                        if not validation["complete"]:
                                            logger.warning(f"⚠️ Описание неполное, отсутствуют категории: {', '.join(validation['missing_categories'])}")
                                        else:
                                            logger.info(f"✅ Описание полное, все категории присутствуют")
                                        
                                        return {
                                            "description": description.strip(),
                                            "success": True,
                                            "error": None,
                                            "validation": validation
                                        }
                                    else:
                                        logger.warning(f"⚠️ LLaVA вернула пустое описание (попытка {attempt + 1}/{max_retries})")
                                        if attempt < max_retries - 1:
                                            await asyncio.sleep(retry_delay * (2 ** attempt))  # Экспоненциальная задержка
                                            continue
                                        return {
                                            "description": "",
                                            "success": False,
                                            "error": "LLaVA вернула пустое описание после всех попыток"
                                        }
                                else:
                                    error_msg = f"Ошибка Ollama API: {response.status_code} - {response.text}"
                                    logger.warning(f"⚠️ {error_msg} (попытка {attempt + 1}/{max_retries})")
                                    last_error = error_msg
                                    if attempt < max_retries - 1:
                                        await asyncio.sleep(retry_delay * (2 ** attempt))  # Экспоненциальная задержка
                                        continue
                                    
                        except httpx.TimeoutException as e:
                            last_error = f"Таймаут анализа изображения (>{settings.OLLAMA_VISION_TIMEOUT}s)"
                            logger.warning(f"⚠️ {last_error} (попытка {attempt + 1}/{max_retries})")
                            
                            # Проверяем, не завершился ли процесс Ollama (только для логирования)
                            ollama_available = await process_manager_service.check_service_available(ServiceType.OLLAMA)
                            if not ollama_available:
                                logger.error(f"❌ Ollama недоступен после таймаута")
                                # НЕ перезапускаем здесь - пусть Resource Manager или Process Manager управляет процессами
                            
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay * (2 ** attempt))  # Экспоненциальная задержка
                                continue
                        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                            last_error = f"Ошибка подключения к Ollama: {e}"
                            logger.error(f"❌ {last_error} (попытка {attempt + 1}/{max_retries})")
                            
                            # Проверяем статус процесса (только для логирования)
                            ollama_available = await process_manager_service.check_service_available(ServiceType.OLLAMA)
                            if not ollama_available:
                                logger.error(f"❌ Ollama недоступен")
                                # НЕ перезапускаем здесь - пусть Resource Manager или Process Manager управляет процессами
                            
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay * (2 ** attempt))  # Экспоненциальная задержка
                                continue
                        except Exception as e:
                            last_error = str(e)
                            logger.warning(f"⚠️ Ошибка при анализе изображения: {e} (попытка {attempt + 1}/{max_retries})")
                            
                            # Проверяем статус процесса (только для логирования)
                            ollama_available = await process_manager_service.check_service_available(ServiceType.OLLAMA)
                            if not ollama_available:
                                logger.error(f"❌ Ollama недоступен после ошибки")
                                # НЕ перезапускаем здесь - пусть Resource Manager или Process Manager управляет процессами
                            
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay * (2 ** attempt))  # Экспоненциальная задержка
                                continue
                    
                    # Если все попытки не удались, возвращаем ошибку
                    logger.error(f"❌ Не удалось проанализировать изображение после {max_retries} попыток: {last_error}")
                    return {
                        "description": "",
                        "success": False,
                        "error": f"Не удалось проанализировать изображение после {max_retries} попыток: {last_error}"
                    }
                        
            except TimeoutError as e:
                logger.error(f"❌ Таймаут ожидания GPU для Ollama (анализ изображения): {e}")
                return {
                    "description": "",
                    "success": False,
                    "error": f"Таймаут ожидания GPU: {str(e)}",
                    "error_type": "gpu_timeout"
                }
            except Exception as e:
                logger.error(f"❌ Ошибка при работе с Resource Manager (анализ изображения): {e}")
                return {
                    "description": "",
                    "success": False,
                    "error": f"Ошибка управления ресурсами: {str(e)}",
                    "error_type": "resource_error"
                }
                
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при анализе изображения: {e}", exc_info=True)
            return {
                "description": "",
                "success": False,
                "error": f"Критическая ошибка: {str(e)}"
            }
    
    async def analyze_img2img_settings(self, description: str, user_id: Optional[int] = None, image_description: Optional[str] = None) -> Dict:
        """
        Анализирует описание пользователя и определяет оптимальные настройки KSampler для img-to-img
        
        Args:
            description: Описание желаемого результата на русском языке
            user_id: ID пользователя (для приоритизации)
            image_description: Описание текущего изображения от LLaVA (опционально)
            
        Returns:
            Словарь с настройками KSampler:
            {
                "denoise": float,  # 0.4-0.9
                "steps": int,      # 25-40
                "cfg": float,      # 1.0 (фиксированно для FLUX)
                "sampler_name": str,  # "euler" или "dpmpp_2m_karras"
                "success": bool,
                "error": Optional[str]
            }
        """
        # Формируем системный промпт с учетом описания изображения
        # Для Flux.1-dev оптимальный denoise: 0.55-0.65 (не 0.8-0.9!)
        if image_description:
            system_prompt = f"""You are an expert in AI image generation settings for Flux.1-dev model img-to-img tasks.
Your task is to analyze the user's description and determine optimal KSampler settings, especially the denoise level.

CURRENT IMAGE DESCRIPTION (from visual analysis):
{image_description}

USER REQUEST:
{description}

You know what the current image looks like and what the user wants to change. Based on this, determine the level of transformation needed.

CRITICAL FOR FLUX.1-DEV: For SIGNIFICANT changes (age, face, major transformations), use denoise 0.75-0.8. For moderate changes, use 0.65-0.75.

You need to determine:
1. Denoise level (0.4-0.8): How much to change the original image
   CRITICAL FOR FLUX.1-DEV - Determine transformation intensity:
   - STRONG TRANSFORMATION (0.75-0.8): Fundamental characteristic changes
     * Appearance/age modifications (any subject: people, animals, objects with age characteristics)
     * Complete structural transformations (changing object type or major features)
     * Complete color/material reversals (opposite colors, completely different materials)
     * Major feature modifications (removing/adding significant elements)
   
   - STRONG CHANGE (0.7-0.75): Significant modifications
     * Major color changes (dominant color replacement)
     * Material type swaps (wood↔metal, stone↔glass, fabric↔leather, etc.)
     * Object removal/addition (removing/adding visible objects)
     * Significant style changes
   
   - MODERATE CHANGE (0.65-0.7): Moderate modifications
     * Color tinting/adjustments (not complete replacement)
     * Style refinements
     * Subtle material adjustments
   
   - MINOR CHANGE (0.4-0.55): Subtle adjustments
     * Quality improvements
     * Minor corrections
     * Slight enhancements
   
   IMPORTANT: For Flux.1-dev, denoise 0.75 is SAFE and provides STRONG transformations while maintaining image structure.
   For significant changes (age, face, major color/material changes), use 0.75-0.8.
   DEFAULT: For significant transformations, use 0.75.
   
2. Steps (25-40): Number of sampling steps (default 30)
   - Use 25-28 for faster generation with good quality
   - Use 30-35 for balanced quality and speed
   - Use 36-40 for highest quality (slower)

3. CFG Scale: Always 1.0 for FLUX models (fixed)

4. Sampler: "euler" (default for img-to-img, works well with Flux) or "dpmpp_2m_karras"

Return ONLY valid JSON in this exact format:
{{
  "denoise": 0.75,
  "steps": 30,
  "cfg": 1.0,
  "sampler_name": "euler"
}}

Decision principles (FOR FLUX.1-DEV):
- STRONG TRANSFORMATION (0.75-0.8): When the request requires changing fundamental characteristics (appearance, age, major structural changes, complete color/material replacement). Examples: changing age/appearance, transforming object type, complete color reversal (black->white).
- STRONG CHANGE (0.7-0.75): When significant modifications are needed (major color changes, material swaps, object removal/addition). Examples: changing dominant color, replacing material type, removing/adding objects.
- MODERATE CHANGE (0.65-0.7): When moderate modifications are needed (color adjustments, style changes). Examples: color tinting, style modifications.
- MINOR CHANGE (0.4-0.55): When only subtle adjustments are needed. Examples: quality improvements, minor corrections.

Analyze the request and current image to determine the transformation level needed.

Do not include any text before or after the JSON. Only return the JSON object."""
            user_message = f"На основе текущего изображения и запроса пользователя определи оптимальные настройки KSampler для Flux.1-dev:\n\nТекущее изображение: {image_description}\n\nЗапрос пользователя: {description}"
        else:
            system_prompt = """You are an expert in AI image generation settings for Flux.1-dev model img-to-img tasks.
Your task is to analyze the user's description and determine optimal KSampler settings, especially the denoise level.

CRITICAL FOR FLUX.1-DEV: For SIGNIFICANT changes (age, face, major transformations), use denoise 0.75-0.8. For moderate changes, use 0.65-0.75.

The user wants to modify an existing image based on their description. You need to determine:
1. Denoise level (0.4-0.8): How much to change the original image
   CRITICAL FOR FLUX.1-DEV - Определи интенсивность трансформации:
   - СИЛЬНАЯ ТРАНСФОРМАЦИЯ (0.75-0.8): Изменение фундаментальных характеристик
     * Изменение внешнего вида/возраста (любой объект: люди, животные, предметы с признаками возраста)
     * Полная структурная трансформация (изменение типа объекта или основных признаков)
     * Полная замена цвета/материала (противоположные цвета, совершенно разные материалы)
     * Значительные изменения признаков (удаление/добавление важных элементов)
   
   - СИЛЬНОЕ ИЗМЕНЕНИЕ (0.7-0.75): Значительные модификации
     * Крупные изменения цвета (замена доминирующего цвета)
     * Замена типа материала (дерево↔металл, камень↔стекло, ткань↔кожа и т.д.)
     * Удаление/добавление объектов (удаление/добавление видимых объектов)
     * Значительные изменения стиля
   
   - УМЕРЕННОЕ ИЗМЕНЕНИЕ (0.65-0.7): Умеренные модификации
     * Тонирование/корректировка цвета (не полная замена)
     * Уточнение стиля
     * Небольшие изменения материала
   
   - НЕЗНАЧИТЕЛЬНОЕ ИЗМЕНЕНИЕ (0.4-0.55): Небольшие корректировки
     * Улучшение качества
     * Небольшие исправления
     * Легкие улучшения
   
   IMPORTANT: For Flux.1-dev, denoise 0.75 is SAFE and provides STRONG transformations while maintaining image structure.
   For significant changes (age, face, major color/material changes), use 0.75-0.8.
   DEFAULT: For significant transformations, use 0.75.
   
2. Steps (25-30): Number of sampling steps (default 30)
   - Use 25-28 for faster generation with good quality
   - Use 30 for balanced quality and speed
   - Flux.1-dev usually doesn't need more than 30 steps

3. CFG Scale: Always 1.0 for FLUX models (fixed)

4. Sampler: "euler" (default for img-to-img, works well with Flux.1-dev)

Return ONLY valid JSON in this exact format:
{
  "denoise": 0.75,
  "steps": 30,
  "cfg": 1.0,
  "sampler_name": "euler"
}

Decision principles (FOR FLUX.1-DEV):
Analyze the request to determine the transformation intensity:

- STRONG TRANSFORMATION (0.75-0.8): Requests that require changing fundamental characteristics:
  * Appearance/age changes (younger, older, different appearance)
  * Complete structural transformations (object type changes)
  * Complete color/material reversals (opposite colors, completely different materials)
  * Major feature modifications (removing/adding significant elements)

- STRONG CHANGE (0.7-0.75): Requests that require significant modifications:
  * Major color changes (dominant color replacement)
  * Material type swaps (wood to metal, stone to glass, etc.)
  * Object removal/addition (removing/adding visible objects)
  * Significant style changes

- MODERATE CHANGE (0.65-0.7): Requests that require moderate modifications:
  * Color tinting/adjustments (not complete replacement)
  * Style refinements
  * Subtle material adjustments

- MINOR CHANGE (0.4-0.55): Requests that require only subtle adjustments:
  * Quality improvements
  * Minor corrections
  * Slight enhancements

Apply these principles to any request, regardless of subject (people, objects, scenes, etc.).

Do not include any text before or after the JSON. Only return the JSON object."""
            user_message = f"Определи оптимальные настройки KSampler для img-to-img на основе этого описания:\n\n{description}"
        
        estimated_vram_mb = 2048
        
        try:
            async with await resource_manager.acquire_gpu(
                service_type=ServiceType.OLLAMA,
                user_id=user_id,
                required_vram_mb=estimated_vram_mb,
                timeout=60
            ) as gpu_lock:
                logger.info(f"🔒 GPU заблокирован для Ollama (анализ настроек img-to-img, ID: {gpu_lock.lock_id[:8]})")
                
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
                            "format": "json"
                        }
                        
                        response = await client.post(
                            f"{self.ollama_url}/api/chat",
                            json=payload
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            content = result.get("message", {}).get("content", "")
                            
                            try:
                                # Убираем markdown code blocks, если есть
                                content = content.strip()
                                if content.startswith("```"):
                                    lines = content.split("\n")
                                    if lines[0].startswith("```"):
                                        lines = lines[1:]
                                    if lines[-1].strip() == "```":
                                        lines = lines[:-1]
                                    content = "\n".join(lines)
                                
                                settings_data = json.loads(content)
                                
                                # Валидация и нормализация значений для Flux.1-dev
                                # Fallback увеличен до 0.75 для более значительных изменений
                                denoise = float(settings_data.get("denoise", 0.75))
                                description_lower = description.lower()
                                
                                # Ключевые слова для изменения возраста/лица (нужен более сильный denoise)
                                age_keywords = [
                                    "молод", "младше", "постар", "старше", "возраст", "омолод",
                                    "морщин", "сед", "седин", "бород", "лицо", "кожа",
                                    "younger", "older", "age", "wrinkle", "wrinkles", "face", "skin", "beard", "gray hair"
                                ]
                                
                                # Для Flux.1-dev базовый максимум denoise: 0.75 (увеличен для более значительных изменений)
                                # Для изменений возраста/лица допускаем до 0.8 для максимального эффекта
                                max_denoise = 0.8 if any(keyword in description_lower for keyword in age_keywords) else 0.75
                                # Минимум также увеличен для более заметных изменений
                                min_denoise = 0.6 if any(keyword in description_lower for keyword in age_keywords) else 0.55
                                denoise = max(min_denoise, min(max_denoise, denoise))
                                
                                # Проверяем, есть ли в описании упоминание цвета
                                color_keywords = ["белый", "красный", "синий", "черный", "зеленый", "желтый", "оранжевый",
                                                 "фиолетовый", "розовый", "коричневый", "серый", "голубой", "цвет",
                                                 "покрасить", "окрасить", "сделать белый", "сделать красный",
                                                 "изменить цвет", "поменять цвет", "другой цвет"]
                                
                                if any(keyword in description_lower for keyword in color_keywords):
                                    # Для Flux.1-dev оптимальный denoise для изменения цвета: 0.65-0.75 (увеличен для лучшего эффекта)
                                    denoise = max(0.65, min(0.75, denoise))
                                    logger.info(f"🎨 Обнаружено изменение цвета в описании, установлен denoise: {denoise} (оптимально для Flux.1-dev)")
                                
                                # Проверяем другие значительные изменения
                                elif denoise < 0.65:
                                    significant_keywords = ["изменить", "переделать", "убрать", "добавить", 
                                                          "заменить", "сделать", "деревянный", "металлический",
                                                          "каменный", "стеклянный"]
                                    if any(keyword in description_lower for keyword in significant_keywords):
                                        denoise = max(0.65, denoise)  # Минимум 0.65 для значительных изменений в Flux.1-dev
                                
                                steps = int(settings_data.get("steps", 30))
                                # Для изменений возраста/лица немного увеличиваем шаги
                                if any(keyword in description_lower for keyword in age_keywords):
                                    steps = max(35, steps)
                                steps = max(25, min(40, steps))  # Ограничиваем диапазон
                                
                                cfg = float(settings_data.get("cfg", 1.0))
                                cfg = 1.0  # Фиксированно для FLUX
                                
                                sampler_name = settings_data.get("sampler_name", "euler")
                                if sampler_name not in ["dpmpp_2m_karras", "euler", "dpmpp_2m", "euler_ancestral"]:
                                    sampler_name = "euler"  # По умолчанию euler для img-to-img (как в шаблоне)
                                
                                logger.info(f"✅ Настройки KSampler определены: denoise={denoise}, steps={steps}, cfg={cfg}, sampler={sampler_name}")
                                
                                return {
                                    "denoise": denoise,
                                    "steps": steps,
                                    "cfg": cfg,
                                    "sampler_name": sampler_name,
                                    "success": True,
                                    "error": None
                                }
                                
                            except (json.JSONDecodeError, ValueError, KeyError) as e:
                                logger.error(f"❌ Ошибка парсинга настроек KSampler: {e}")
                                logger.debug(f"Ответ от Ollama: {content[:500]}")
                                
                                # Fallback: используем значения по умолчанию для Flux.1-dev
                                # Проверяем на изменение возраста/лица
                                description_lower = description.lower()
                                age_keywords = [
                                    "молод", "младше", "постар", "старше", "возраст", "омолод",
                                    "морщин", "сед", "седин", "бород", "лицо", "кожа",
                                    "younger", "older", "age", "wrinkle", "wrinkles", "face", "skin", "beard", "gray hair"
                                ]
                                # Для Flux.1-dev оптимальный denoise: 0.6, но для возраста/лица повышаем до 0.7
                                default_denoise = 0.7 if any(keyword in description_lower for keyword in age_keywords) else 0.6
                                return {
                                    "denoise": default_denoise,
                                    "steps": 30,
                                    "cfg": 1.0,
                                    "sampler_name": "euler",
                                    "success": True,
                                    "error": f"Использованы значения по умолчанию для Flux.1-dev (ошибка парсинга: {str(e)})"
                                }
                                
                        else:
                            error_msg = f"Ошибка Ollama API: {response.status_code} - {response.text}"
                            logger.error(f"❌ {error_msg}")
                            # Fallback: используем значения по умолчанию (увеличен denoise для лучших результатов)
                            return {
                                "denoise": 0.6,
                                "steps": 30,
                                "cfg": 1.0,
                                "sampler_name": "dpmpp_2m",
                                "success": True,
                                "error": f"Использованы значения по умолчанию ({error_msg})"
                            }
                            
                except httpx.TimeoutException:
                    logger.error("❌ Таймаут при запросе к Ollama")
                    return {
                        "denoise": 0.7,
                        "steps": 30,
                        "cfg": 1.0,
                        "sampler_name": "dpmpp_2m",
                        "success": True,
                        "error": "Использованы значения по умолчанию (таймаут)"
                    }
                except Exception as e:
                    logger.error(f"❌ Ошибка при анализе настроек: {e}")
                    return {
                        "denoise": 0.7,
                        "steps": 30,
                        "cfg": 1.0,
                        "sampler_name": "dpmpp_2m",
                        "success": True,
                        "error": f"Использованы значения по умолчанию ({str(e)})"
                    }
                    
        except TimeoutError as e:
            logger.error(f"❌ Таймаут ожидания GPU для Ollama (анализ настроек): {e}")
            return {
                "denoise": 0.7,
                "steps": 30,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m",
                "success": True,
                "error": f"Использованы значения по умолчанию (таймаут GPU: {str(e)})"
            }
        except Exception as e:
            logger.error(f"❌ Ошибка при работе с Resource Manager: {e}")
            return {
                "denoise": 0.7,
                "steps": 30,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m",
                "success": True,
                "error": f"Использованы значения по умолчанию (ошибка управления ресурсами: {str(e)})"
            }


# Глобальный экземпляр сервиса
prompt_service = PromptService()
