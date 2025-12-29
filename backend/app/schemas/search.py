"""
Схемы данных для поиска
"""
from pydantic import BaseModel
from typing import List, Optional


class SearchResult(BaseModel):
    """Результат поиска"""
    title: str
    url: str
    content: str
    score: float


class SearchRequest(BaseModel):
    """Запрос на поиск с сообщением"""
    message: str
    chat_id: int
    use_search: bool = True


class SearchMetadata(BaseModel):
    """Метаданные о поиске"""
    query: str
    sources: List[str]
    results_count: int
    success: bool
    error: Optional[str] = None


class SearchChatResponse(BaseModel):
    """Ответ с метаданными поиска"""
    content: str
    search_metadata: Optional[SearchMetadata] = None

