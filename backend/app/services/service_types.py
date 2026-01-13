"""
Типы сервисов для управления ресурсами GPU
"""
from enum import Enum


class ServiceType(Enum):
    """Типы сервисов, использующих GPU"""
    COMFYUI = "comfyui"
    OLLAMA = "ollama"
    OTHER = "other"

