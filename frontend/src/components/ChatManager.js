import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '../AuthContext';
import {
  RiAddLine,
  RiChat3Line,
  RiPushpinLine,
  RiDeleteBinLine,
  RiEditLine,
  RiCheckLine,
  RiCloseLine,
  RiLoader4Line,
  RiMoreLine,
  RiUserLine,
  RiSettings3Line,
  RiQuestionLine,
  RiMenuLine
} from 'react-icons/ri';
import './ChatManager.css';

const ChatManager = ({ onChatSelect, currentChatId, refreshTrigger, chats: externalChats, isHidden = false, onToggleSidebar, onOpenProfile, onOpenSettings }) => {
  const { user } = useAuth();
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingChat, setEditingChat] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [creatingChat, setCreatingChat] = useState(false);
  const [hoveredChat, setHoveredChat] = useState(null);
  const [openMenuChat, setOpenMenuChat] = useState(null);

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

  useEffect(() => {
    loadChats();
  }, [loadChats]);

  useEffect(() => {
    if (refreshTrigger > 0) {
      loadChats();
    }
  }, [refreshTrigger, loadChats]);

  useEffect(() => {
    if (externalChats && externalChats.length > 0) {
      setChats(externalChats);
    }
  }, [externalChats]);

  // Закрытие меню при клике вне его
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (openMenuChat && !event.target.closest('.chat-actions')) {
        setOpenMenuChat(null);
      }
    };

    if (openMenuChat) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [openMenuChat]);

  const createNewChat = async () => {
    if (loading || creatingChat) {
      return;
    }
    
    setCreatingChat(true);
    
    try {
      const token = localStorage.getItem('token');
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

  // Группировка чатов по датам
  const groupedChats = useMemo(() => {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    const thirtyDaysAgo = new Date(today);
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    const pinned = [];
    const todayChats = [];
    const yesterdayChats = [];
    const recentChats = [];
    const olderChats = [];

    chats.forEach(chat => {
      if (chat.pinned) {
        pinned.push(chat);
        return;
      }

      const chatDate = new Date(chat.last_message_at || chat.updated_at || chat.created_at);
      const chatDateOnly = new Date(chatDate.getFullYear(), chatDate.getMonth(), chatDate.getDate());

      if (chatDateOnly.getTime() === today.getTime()) {
        todayChats.push(chat);
      } else if (chatDateOnly.getTime() === yesterday.getTime()) {
        yesterdayChats.push(chat);
      } else if (chatDate >= thirtyDaysAgo) {
        recentChats.push(chat);
      } else {
        olderChats.push(chat);
      }
    });

    const groups = [];
    if (pinned.length > 0) {
      groups.push({ label: 'Закрепленные', chats: pinned });
    }
    if (todayChats.length > 0) {
      groups.push({ label: 'Сегодня', chats: todayChats });
    }
    if (yesterdayChats.length > 0) {
      groups.push({ label: 'Вчера', chats: yesterdayChats });
    }
    if (recentChats.length > 0) {
      groups.push({ label: 'Предыдущие 30 дней', chats: recentChats });
    }
    if (olderChats.length > 0) {
      groups.push({ label: 'Ранее', chats: olderChats });
    }

    return groups;
  }, [chats]);

  const truncateMessage = (message, maxLength = 50) => {
    if (!message || message.length <= maxLength) {
      return message;
    }
    return message.slice(0, maxLength) + '...';
  };

  if (loading) {
    return (
      <div className={`chat-manager ${isHidden ? 'hidden' : ''}`}>
        <div className="chat-manager-header">
          <button className="sidebar-toggle-btn" onClick={onToggleSidebar} title="Свернуть панель">
            <RiCloseLine />
          </button>
          <button className="new-chat-btn-header" disabled>
            <RiAddLine />
            <span>Новый чат</span>
          </button>
        </div>
        <div className="loading-chats">
          <div className="skeleton-chats-container">
            {[...Array(5)].map((_, index) => (
              <div key={index} className="skeleton-chat-item">
                <div className="skeleton-chat-content">
                  <div className="skeleton-chat-title"></div>
                  <div className="skeleton-chat-message"></div>
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
      {/* Header */}
      <div className="chat-manager-header">
        <button className="sidebar-toggle-btn" onClick={onToggleSidebar} title="Свернуть панель">
          <RiCloseLine />
        </button>
        <button 
          className="new-chat-btn-header"
          onClick={createNewChat}
          disabled={creatingChat}
          title="Создать новый чат"
        >
          <RiAddLine />
          <span>Новый чат</span>
        </button>
      </div>

      {error && (
        <div className="error-message">
          {error}
          <button onClick={() => setError('')}>×</button>
        </div>
      )}

      {/* Body - Scrollable chat list */}
      <div className="chats-list-container">
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
            groupedChats.map((group, groupIndex) => (
              <div key={groupIndex} className="chat-group">
                <div className="chat-group-header">{group.label}</div>
                {group.chats.map(chat => (
                  <div 
                    key={chat.id} 
                    className={`chat-item ${currentChatId === chat.id ? 'active' : ''}`}
                    onClick={() => onChatSelect(chat.id)}
                    onMouseEnter={() => setHoveredChat(chat.id)}
                    onMouseLeave={() => setHoveredChat(null)}
                  >
                    <div className="chat-content">
                      {editingChat === chat.id ? (
                        <div className="edit-chat">
                          <input
                            type="text"
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            onKeyPress={(e) => {
                              if (e.key === 'Enter') {
                                saveEdit(chat.id);
                              } else if (e.key === 'Escape') {
                                cancelEdit();
                              }
                            }}
                            onBlur={() => saveEdit(chat.id)}
                            autoFocus
                            className="edit-input"
                            onClick={(e) => e.stopPropagation()}
                          />
                        </div>
                      ) : (
                        <>
                          <div className="chat-title">
                            {chat.pinned && <RiPushpinLine className="pin-icon" />}
                            <span className="chat-title-text">{chat.title}</span>
                          </div>
                          {chat.last_message && (
                            <div className="chat-preview">
                              {truncateMessage(chat.last_message)}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                    
                    {editingChat !== chat.id && (
                      <div className={`chat-actions ${hoveredChat === chat.id ? 'visible' : ''}`}>
                        <button
                          className="action-btn more-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setOpenMenuChat(openMenuChat === chat.id ? null : chat.id);
                          }}
                          title="Дополнительно"
                        >
                          <RiMoreLine />
                        </button>
                        {openMenuChat === chat.id && (
                          <div className="chat-actions-menu" onClick={(e) => e.stopPropagation()}>
                            <button
                              className="action-menu-item"
                              onClick={(e) => {
                                e.stopPropagation();
                                togglePin(chat.id, Boolean(chat.pinned));
                                setOpenMenuChat(null);
                              }}
                              title={chat.pinned ? 'Открепить' : 'Закрепить'}
                            >
                              <RiPushpinLine />
                              <span>{chat.pinned ? 'Открепить' : 'Закрепить'}</span>
                            </button>
                            <button
                              className="action-menu-item"
                              onClick={(e) => {
                                e.stopPropagation();
                                startEdit(chat);
                                setOpenMenuChat(null);
                              }}
                              title="Переименовать"
                            >
                              <RiEditLine />
                              <span>Переименовать</span>
                            </button>
                            <button
                              className="action-menu-item delete"
                              onClick={(e) => {
                                e.stopPropagation();
                                deleteChat(chat.id);
                                setOpenMenuChat(null);
                              }}
                              title="Удалить"
                            >
                              <RiDeleteBinLine />
                              <span>Удалить</span>
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="chat-manager-footer">
        {onOpenProfile && (
          <button className="footer-btn" onClick={onOpenProfile} title={user?.name || 'Профиль'}>
            <RiUserLine />
            <span>{user?.name || 'Профиль'}</span>
          </button>
        )}
        {onOpenSettings && (
          <button className="footer-btn" onClick={onOpenSettings} title="Настройки">
            <RiSettings3Line />
            <span>Настройки</span>
          </button>
        )}
        <button className="footer-btn" onClick={() => {/* Open help */}} title="Помощь">
          <RiQuestionLine />
          <span>Помощь</span>
        </button>
      </div>
    </div>
  );
};

export default ChatManager;
