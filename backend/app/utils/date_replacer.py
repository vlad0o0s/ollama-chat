"""
Утилита для замены временных слов на реальную дату в промптах
"""
import re
from datetime import datetime, timedelta
from typing import Dict


def replace_temporal_words(text: str) -> str:
    """
    Заменяет временные слова на реальную дату в формате DD.MM.YYYY
    
    Поддерживаемые слова:
    - сегодня, сегодняшний, сегодняшняя, сегодняшнее
    - вчера, вчерашний, вчерашняя, вчерашнее
    - завтра, завтрашний, завтрашняя, завтрашнее
    - новости на сегодня, новости сегодня, новости за сегодня
    - события сегодня, события на сегодня
    - и другие похожие конструкции
    
    Args:
        text: Текст для обработки
        
    Returns:
        Текст с замененными временными словами на реальную дату
    """
    if not text:
        return text
    
    # Получаем текущую дату
    today = datetime.now()
    today_str = today.strftime("%d.%m.%Y")
    yesterday = today - timedelta(days=1)
    yesterday_str = yesterday.strftime("%d.%m.%Y")
    tomorrow = today + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%d.%m.%Y")
    
    # Сначала обрабатываем сложные конструкции (чтобы они не были заменены простыми словами)
    result = text
    
    # "что происходит сегодня" -> "что происходит 28.03.2026"
    result = re.sub(
        r'\b(что\s+происходит|что\s+случилось|что\s+случается|что\s+было)\s+сегодня\b',
        rf'\1 {today_str}',
        result,
        flags=re.IGNORECASE
    )
    
    # "новости на сегодня" -> "новости на 28.03.2026"
    result = re.sub(
        r'\b(новости|события|погода|курс|цены|котировки|аналитика|обзор|итоги|сводка|дайджест)\s+(на|за)\s+сегодня\b',
        rf'\1 на {today_str}',
        result,
        flags=re.IGNORECASE
    )
    
    # "новости сегодня" -> "новости на 28.03.2026"
    result = re.sub(
        r'\b(новости|события|погода|курс|цены|котировки|аналитика|обзор|итоги|сводка|дайджест)\s+сегодня\b',
        rf'\1 на {today_str}',
        result,
        flags=re.IGNORECASE
    )
    
    # "на сегодня" -> "на 28.03.2026"
    result = re.sub(
        r'\bна\s+сегодня\b',
        f'на {today_str}',
        result,
        flags=re.IGNORECASE
    )
    
    # "за сегодня" -> "за 28.03.2026"
    result = re.sub(
        r'\bза\s+сегодня\b',
        f'за {today_str}',
        result,
        flags=re.IGNORECASE
    )
    
    # "по сегодня" -> "по 28.03.2026"
    result = re.sub(
        r'\bпо\s+сегодня\b',
        f'по {today_str}',
        result,
        flags=re.IGNORECASE
    )
    
    # Теперь обрабатываем простые слова (после сложных конструкций)
    replacements: Dict[str, str] = {
        # Сегодня
        r'\bсегодняшний\b': f'на {today_str}',
        r'\bсегодняшняя\b': f'на {today_str}',
        r'\bсегодняшнее\b': f'на {today_str}',
        r'\bсегодняшние\b': f'на {today_str}',
        r'\bсегодня\b': today_str,
        
        # Вчера
        r'\bвчерашний\b': f'на {yesterday_str}',
        r'\bвчерашняя\b': f'на {yesterday_str}',
        r'\bвчерашнее\b': f'на {yesterday_str}',
        r'\bвчерашние\b': f'на {yesterday_str}',
        r'\bвчера\b': yesterday_str,
        
        # Завтра
        r'\bзавтрашний\b': f'на {tomorrow_str}',
        r'\bзавтрашняя\b': f'на {tomorrow_str}',
        r'\bзавтрашнее\b': f'на {tomorrow_str}',
        r'\bзавтрашние\b': f'на {tomorrow_str}',
        r'\bзавтра\b': tomorrow_str,
    }
    
    # Применяем замены (регистронезависимо)
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result

