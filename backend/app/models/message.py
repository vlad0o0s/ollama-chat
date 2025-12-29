from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, CheckConstraint, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base


class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    message_type = Column(String(20), default='text', nullable=False)  # 'text' or 'image'
    image_url = Column(String(500), nullable=True)  # URL изображения для сообщений типа 'image'
    image_metadata = Column(JSON, nullable=True)  # Метаданные изображения (промпты, параметры)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Связи
    chat = relationship("Chat", back_populates="messages")
    
    # Ограничения
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="check_role"),
        CheckConstraint("message_type IN ('text', 'image')", name="check_message_type"),
    )

