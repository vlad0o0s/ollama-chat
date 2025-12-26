import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../AuthContext';
import {
  RiAddLine,
  RiChat3Line,
  RiPushpinLine,
  RiDeleteBinLine,
  RiEditLine,
  RiCheckLine,
  RiCloseLine,
  RiLoader4Line
} from 'react-icons/ri';
import './ChatManager.css';

const ChatManager = ({ onChatSelect, currentChatId, refreshTrigger, chats: externalChats, isHidden = false }) => {
  const { user } = useAuth();
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingChat, setEditingChat] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [creatingChat, setCreatingChat] = useState(false);

  const loadChats = useCallback(async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      const response = await fetch('/api/chats', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const chatsData = await response.json();
        setChats(chatsData);
      } else {
        setError('Ошибка загрузки чатов');
      }
    } catch (error) {
      console.error('ChatManager: Ошибка загрузки чатов:', error);
      setError('Ошибка сети');
    } finally {
      setLoading(false);
    }
  }, []);

  // Загрузка чатов при монтировании компонента
  useEffect(() => {
    loadChats();
  }, [loadChats]);

  // Перезагрузка чатов при изменении refreshTrigger
  useEffect(() => {
    if (refreshTrigger > 0) {
      loadChats();
    }
  }, [refreshTrigger, loadChats]);

  // Обновление чатов при изменении внешних чатов
  useEffect(() => {
    if (externalChats && externalChats.length > 0) {
      setChats(externalChats);
    }
  }, [externalChats]);

  const createNewChat = async () => {
    if (loading || creatingChat) {
      return;
    }
    
    setCreatingChat(true);
    
    // Дополнительная защита - блокируем кнопку
    const button = document.querySelector('.new-chat-btn');
    if (button) {
      button.disabled = true;
    }
    
    try {
      const token = localStorage.getItem('token');
      
      // Создаем новый чат (сервер сам удалит пустые чаты)
      const response = await fetch('/api/chats', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          title: 'Новый чат'
        })
      });

      if (response.ok) {
        const newChat = await response.json();
        // Перезагружаем список чатов, чтобы получить актуальное состояние
        await loadChats();
        onChatSelect(newChat.id);
      } else {
        setError('Ошибка создания чата');
      }
    } catch (error) {
      console.error('ChatManager: Ошибка создания чата:', error);
      setError('Ошибка сети');
    } finally {
      setCreatingChat(false);
      // Разблокируем кнопку
      if (button) {
        button.disabled = false;
      }
    }
  };

  const deleteChat = async (chatId) => {
    if (!window.confirm('Вы уверены, что хотите удалить этот чат?')) {
      return;
    }

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/chats/${chatId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        setChats(prev => prev.filter(chat => chat.id !== chatId));
        if (currentChatId === chatId) {
          onChatSelect(null);
        }
      } else {
        setError('Ошибка удаления чата');
      }
    } catch (error) {
      console.error('Ошибка удаления чата:', error);
      setError('Ошибка сети');
    }
  };

  const togglePin = async (chatId, currentPinned) => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/chats/${chatId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          pinned: !currentPinned
        })
      });

      if (response.ok) {
        setChats(prev => prev.map(chat => 
          chat.id === chatId ? { ...chat, pinned: !currentPinned } : chat
        ));
      } else {
        setError('Ошибка обновления чата');
      }
    } catch (error) {
      console.error('Ошибка обновления чата:', error);
      setError('Ошибка сети');
    }
  };

  const startEdit = (chat) => {
    setEditingChat(chat.id);
    setEditTitle(chat.title);
  };

  const saveEdit = async (chatId) => {
    if (!editTitle.trim()) return;

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/chats/${chatId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          title: editTitle.trim()
        })
      });

      if (response.ok) {
        setChats(prev => prev.map(chat => 
          chat.id === chatId ? { ...chat, title: editTitle.trim() } : chat
        ));
        setEditingChat(null);
        setEditTitle('');
      } else {
        setError('Ошибка обновления чата');
      }
    } catch (error) {
      console.error('Ошибка обновления чата:', error);
      setError('Ошибка сети');
    }
  };

  const cancelEdit = () => {
    setEditingChat(null);
    setEditTitle('');
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffTime = Math.abs(now - date);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays === 1) {
      return 'Сегодня';
    } else if (diffDays === 2) {
      return 'Вчера';
    } else if (diffDays <= 7) {
      return `${diffDays - 1} дн. назад`;
    } else {
      return date.toLocaleDateString('ru-RU');
    }
  };

  const truncateMessage = (message, maxLength = 20) => {
    if (!message || message.length <= maxLength) {
      return message;
    }
    
    // Ищем подходящее место для обрезки (конец слова)
    let truncated = message.slice(0, maxLength);
    const lastSpace = truncated.lastIndexOf(' ');
    
    // Если есть подходящее место для обрезки по пробелу
    if (lastSpace > maxLength * 0.7) {
      truncated = truncated.slice(0, lastSpace);
    }
    
    return truncated + '...';
  };

  if (loading) {
    return (
      <div className="chat-manager">
        <div className="chat-manager-header">
          <h3>
            <RiChat3Line style={{ marginRight: '8px', color: '#8e8ea0' }} />
            Чаты
          </h3>
        </div>
        <div className="loading-chats">
          <div className="skeleton-chats-container">
            {/* Скелетон элементы для чатов */}
            {[...Array(5)].map((_, index) => (
              <div key={index} className="skeleton-chat-item">
                <div className="skeleton-chat-content">
                  <div className="skeleton-chat-title"></div>
                  <div className="skeleton-chat-meta">
                    <div className="skeleton-chat-message"></div>
                    <div className="skeleton-chat-time"></div>
                  </div>
                </div>
                <div className="skeleton-chat-actions">
                  <div className="skeleton-action-btn"></div>
                  <div className="skeleton-action-btn"></div>
                  <div className="skeleton-action-btn"></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`chat-manager ${isHidden ? 'hidden' : ''}`}>
      <div className="chat-manager-header">
        <h3>
          <RiChat3Line style={{ marginRight: '8px', color: '#8e8ea0' }} />
          Чаты
        </h3>
        {loading || creatingChat ? (
          <div className="skeleton-button" style={{width: '32px', height: '32px', borderRadius: '6px'}}></div>
        ) : (
          <button 
            className="new-chat-btn"
            onClick={createNewChat}
            title="Создать новый чат"
          >
            <RiAddLine />
          </button>
        )}
      </div>

      {error && (
        <div className="error-message">
          {error}
          <button onClick={() => setError('')}>×</button>
        </div>
      )}

      <div className="chats-list">
        {chats.length === 0 ? (
          <div className="no-chats">
            <RiChat3Line className="no-chats-icon" />
            <p>У вас пока нет чатов</p>
            <button className="create-first-chat" onClick={createNewChat}>
              Создать первый чат
            </button>
          </div>
        ) : (
          chats.map(chat => (
            <div 
              key={chat.id} 
              className={`chat-item ${currentChatId === chat.id ? 'active' : ''} ${Boolean(chat.pinned) ? 'pinned' : ''}`}
              onClick={() => onChatSelect(chat.id)}
            >
              <div className="chat-content">
                {editingChat === chat.id ? (
                  <div className="edit-chat">
                    <input
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyPress={(e) => e.key === 'Enter' && saveEdit(chat.id)}
                      autoFocus
                      className="edit-input"
                    />
                    <div className="edit-actions">
                      <button 
                        className="save-btn"
                        onClick={() => saveEdit(chat.id)}
                        title="Сохранить"
                      >
                        <RiCheckLine />
                      </button>
                      <button 
                        className="cancel-btn"
                        onClick={cancelEdit}
                        title="Отменить"
                      >
                        <RiCloseLine />
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="chat-title">
                      {Boolean(chat.pinned) && <RiPushpinLine className="pin-icon" />}
                      <span>{chat.title}</span>
                    </div>
                    <div className="chat-meta">
                      <span className="last-message">
                        {chat.last_message ? truncateMessage(chat.last_message) : 'Новый чат'}
                      </span>
                      <span className="last-message-time">
                        {chat.last_message_at ? formatDate(chat.last_message_at) : ''}
                      </span>
                    </div>
                  </>
                )}
              </div>
              
              {editingChat !== chat.id && (
                <div className="chat-actions">
                  <button
                    className="action-btn pin-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      togglePin(chat.id, Boolean(chat.pinned));
                    }}
                    title={Boolean(chat.pinned) ? 'Открепить' : 'Закрепить'}
                  >
                    <RiPushpinLine className={Boolean(chat.pinned) ? 'pinned' : ''} />
                  </button>
                  <button
                    className="action-btn edit-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      startEdit(chat);
                    }}
                    title="Редактировать"
                  >
                    <RiEditLine />
                  </button>
                  <button
                    className="action-btn delete-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteChat(chat.id);
                    }}
                    title="Удалить"
                  >
                    <RiDeleteBinLine />
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default ChatManager;
