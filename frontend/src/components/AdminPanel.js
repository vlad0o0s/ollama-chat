import React, { useState, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { 
  RiUserLine, 
  RiCloseLine,
  RiEditLine,
  RiDeleteBinLine,
  RiShieldUserLine,
  RiUserStarLine,
  RiLoader4Line,
  RiRefreshLine
} from 'react-icons/ri';
import './AdminPanel.css';

const AdminPanel = ({ onClose }) => {
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [editingUser, setEditingUser] = useState(null);
  const [newRole, setNewRole] = useState('');

  // Загрузка списка пользователей
  const loadUsers = async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      const response = await fetch('/api/admin/users', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const usersData = await response.json();
        setUsers(usersData);
      } else {
        setError('Ошибка загрузки пользователей');
      }
    } catch (error) {
      console.error('Ошибка загрузки пользователей:', error);
      setError('Ошибка сети');
    } finally {
      setLoading(false);
    }
  };

  // Загрузка пользователей при открытии панели
  useEffect(() => {
    loadUsers();
  }, []);

  // Смена роли пользователя
  const changeUserRole = async (userId, role) => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/admin/users/${userId}/role`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ role })
      });

      if (response.ok) {
        setSuccess('Роль пользователя успешно изменена');
        setEditingUser(null);
        setNewRole('');
        await loadUsers();
        setTimeout(() => setSuccess(''), 3000);
      } else {
        setError('Ошибка изменения роли');
      }
    } catch (error) {
      console.error('Ошибка изменения роли:', error);
      setError('Ошибка сети');
    }
  };

  // Удаление пользователя
  const deleteUser = async (userId, userName) => {
    if (!window.confirm(`Вы уверены, что хотите удалить пользователя "${userName}"? Это действие нельзя отменить.`)) {
      return;
    }

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/admin/users/${userId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        setSuccess('Пользователь успешно удален');
        await loadUsers();
        setTimeout(() => setSuccess(''), 3000);
      } else {
        setError('Ошибка удаления пользователя');
      }
    } catch (error) {
      console.error('Ошибка удаления пользователя:', error);
      setError('Ошибка сети');
    }
  };

  // Начало редактирования роли
  const startEditRole = (user) => {
    setEditingUser(user.id);
    setNewRole(user.role);
  };

  // Отмена редактирования
  const cancelEdit = () => {
    setEditingUser(null);
    setNewRole('');
  };


  // Форматирование даты
  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('ru-RU', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Получение иконки роли
  const getRoleIcon = (role) => {
    return role === 'admin' ? <RiShieldUserLine /> : <RiUserLine />;
  };

  // Получение цвета роли
  const getRoleColor = (role) => {
    return role === 'admin' ? '#ff8c00' : '#8e8ea0';
  };

  return (
    <div className="admin-panel-overlay" onClick={onClose}>
      <div className="admin-panel-card" onClick={(e) => e.stopPropagation()}>
        <div className="admin-panel-header">
          <div className="admin-panel-title">
            <RiShieldUserLine className="admin-icon" />
            <h3>Панель администратора</h3>
          </div>
          <button onClick={onClose} className="close-btn">
            <RiCloseLine />
          </button>
        </div>

        <div className="admin-panel-content">
          {error && (
            <div className="error-message">
              {error}
              <button onClick={() => setError('')}>×</button>
            </div>
          )}

          {success && (
            <div className="success-message">
              {success}
            </div>
          )}

          <div className="admin-panel-actions">
            <button onClick={loadUsers} className="refresh-btn" disabled={loading}>
              <RiRefreshLine />
              Обновить
            </button>
          </div>

          {loading ? (
            <div className="loading-users">
              <RiLoader4Line className="loading-icon" />
              <span>Загрузка пользователей...</span>
            </div>
          ) : (
            <div className="users-list">
              <div className="users-header">
                <span>Пользователи ({users.length})</span>
              </div>
              
              {users.length === 0 ? (
                <div className="no-users">
                  <RiUserLine className="no-users-icon" />
                  <p>Пользователи не найдены</p>
                </div>
              ) : (
                users.map(userItem => (
                  <div key={userItem.id} className="user-item">
                    <div className="user-info">
                      <div className="user-avatar">
                        {getRoleIcon(userItem.role)}
                      </div>
                      <div className="user-details">
                        <div className="user-name">
                          {userItem.name}
                          {userItem.id === user.id && <span className="current-user">(Вы)</span>}
                        </div>
                        <div className="user-meta">
                          <span className="user-role" style={{ color: getRoleColor(userItem.role) }}>
                            {userItem.role === 'admin' ? 'Администратор' : 'Пользователь'}
                          </span>
                          <span className="user-date">
                            {formatDate(userItem.created_at)}
                          </span>
                        </div>
                      </div>
                    </div>
                    
                    <div className="user-actions">
                      {editingUser === userItem.id ? (
                        <div className="edit-role-container">
                          <select
                            value={newRole}
                            onChange={(e) => setNewRole(e.target.value)}
                            className="role-select"
                          >
                            <option value="user">Пользователь</option>
                            <option value="admin">Администратор</option>
                          </select>
                          <button
                            onClick={() => changeUserRole(userItem.id, newRole)}
                            className="action-btn save"
                            title="Сохранить"
                          >
                            <RiEditLine />
                          </button>
                          <button
                            onClick={cancelEdit}
                            className="action-btn cancel"
                            title="Отменить"
                          >
                            <RiCloseLine />
                          </button>
                        </div>
                      ) : (
                        <>
                          <button
                            onClick={() => startEditRole(userItem)}
                            className="action-btn edit"
                            title="Изменить роль"
                            disabled={userItem.id === user.id}
                          >
                            <RiEditLine />
                          </button>
                          <button
                            onClick={() => deleteUser(userItem.id, userItem.name)}
                            className="action-btn delete"
                            title="Удалить пользователя"
                            disabled={userItem.id === user.id}
                          >
                            <RiDeleteBinLine />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AdminPanel;
