"""
Сервис для работы с Tavily Search API
"""
from typing import List, Dict, Optional
import asyncio
from tavily import TavilyClient
from ..config import settings
import logging

logger = logging.getLogger(__name__)


class SearchService:
    """Сервис для выполнения поиска в интернете через Tavily API"""
    
    def __init__(self):
        """Инициализация сервиса поиска"""
        if not settings.TAVILY_API_KEY:
            logger.warning("TAVILY_API_KEY не установлен. Поиск будет недоступен.")
            self.client = None
        else:
            self.client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    
    async def search(self, query: str) -> Dict:
        """
        Выполняет поиск по запросу
        
        Args:
            query: Поисковый запрос
            
        Returns:
            Словарь с результатами поиска:
            {
                "query": str,
                "results": List[Dict],
                "sources": List[str],
                "success": bool,
                "error": Optional[str]
            }
        """
        if not self.client:
            return {
                "query": query,
                "results": [],
                "sources": [],
                "success": False,
                "error": "Tavily API key не настроен"
            }
        
        try:
            # Выполняем поиск с таймаутом
            search_result = await asyncio.wait_for(
                self._perform_search(query),
                timeout=settings.TAVILY_SEARCH_TIMEOUT
            )
            
            # Форматируем результаты
            formatted_results = self._format_results(search_result)
            
            return {
                "query": query,
                "results": formatted_results,
                "sources": [r["url"] for r in formatted_results],
                "success": True,
                "error": None
            }
            
        except asyncio.TimeoutError:
            logger.error(f"Таймаут поиска для запроса: {query}")
            return {
                "query": query,
                "results": [],
                "sources": [],
                "success": False,
                "error": "Таймаут поиска"
            }
        except Exception as e:
            logger.error(f"Ошибка поиска для запроса '{query}': {e}")
            return {
                "query": query,
                "results": [],
                "sources": [],
                "success": False,
                "error": str(e)
            }
    
    async def _perform_search(self, query: str) -> Dict:
        """Выполняет синхронный поиск в отдельном потоке"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.client.search(
                query=query,
                search_depth=settings.TAVILY_SEARCH_DEPTH,
                max_results=settings.TAVILY_MAX_RESULTS
            )
        )
    
    def _format_results(self, search_result: Dict) -> List[Dict]:
        """
        Форматирует результаты поиска для удобного использования
        
        Args:
            search_result: Результат от Tavily API
            
        Returns:
            Список отформатированных результатов
        """
        formatted = []
        
        if not search_result or "results" not in search_result:
            return formatted
        
        for result in search_result.get("results", []):
            formatted.append({
                "title": result.get("title", "Без заголовка"),
                "url": result.get("url", ""),
                "content": result.get("content", ""),
                "score": result.get("score", 0.0)
            })
        
        return formatted
    
    def format_search_context(self, search_data: Dict) -> str:
        """
        Форматирует результаты поиска для передачи в LLM как контекст
        
        Args:
            search_data: Результаты поиска от метода search()
            
        Returns:
            Отформатированная строка с контекстом для LLM
        """
        if not search_data.get("success") or not search_data.get("results"):
            return ""
        
        query = search_data.get("query", "")
        results = search_data.get("results", [])
        
        context = f"[Информация из интернета по запросу \"{query}\":]\n\n"
        
        for i, result in enumerate(results, 1):
            title = result.get("title", "Без заголовка")
            url = result.get("url", "")
            content = result.get("content", "")
            
            # Ограничиваем длину контента
            max_content_length = 500
            if len(content) > max_content_length:
                content = content[:max_content_length] + "..."
            
            context += f"{i}. [{title}] (Источник: {url})\n"
            context += f"   {content}\n\n"
        
        context += "[Используй эту информацию для ответа на вопрос пользователя. Указывай источники в ответе, если используешь информацию из них.]\n\n"
        
        return context


# Глобальный экземпляр сервиса
search_service = SearchService()

