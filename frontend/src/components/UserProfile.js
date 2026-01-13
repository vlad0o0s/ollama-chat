import React, { useState } from 'react';
import { useAuth } from '../AuthContext';
import { 
  RiUserLine, 
  RiLogoutBoxLine,
  RiEditLine,
  RiCloseLine,
  RiChat3Line
} from 'react-icons/ri';
import './UserProfile.css';

const UserProfile = ({ onClose }) => {
  const { user, logout, updateProfile } = useAuth();
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [formData, setFormData] = useState({
    name: user?.name || ''
  });

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    });
    setError('');
    setSuccess('');
  };

  const handleSave = async () => {
    setLoading(true);
    setError('');
    setSuccess('');

    const result = await updateProfile(formData);
    
    if (result.success) {
      setSuccess('Профиль успешно обновлен');
      setIsEditing(false);
    } else {
      setError(result.error);
    }
    
    setLoading(false);
  };

  const handleCancel = () => {
    setFormData({
      name: user?.name || ''
    });
    setIsEditing(false);
    setError('');
    setSuccess('');
  };

  const handleLogout = () => {
    logout();
    onClose();
  };

  return (
    <div className="user-profile-overlay" onClick={onClose}>
      <div className="user-profile-card" onClick={(e) => e.stopPropagation()}>
        <div className="profile-header">
          <div className="profile-avatar">
            <RiUserLine />
          </div>
          <h3>Профиль пользователя</h3>
          <button onClick={onClose} className="close-btn">
            <RiCloseLine />
          </button>
        </div>

        <div className="profile-content">
          {error && (
            <div className="error-message">
              {error}
            </div>
          )}

          {success && (
            <div className="success-message">
              {success}
            </div>
          )}

          <div className="profile-info">
            <div className="info-group">
              <label>
                <RiUserLine className="label-icon" />
                Имя
              </label>
              {isEditing ? (
                <input
                  type="text"
                  name="name"
                  value={formData.name}
                  onChange={handleChange}
                  className="profile-input"
                  onKeyPress={(e) => e.key === 'Enter' && handleSave()}
                  onBlur={handleSave}
                  autoFocus
                />
              ) : (
                <div className="info-value-container">
                  <div className="info-value">{user?.name}</div>
                  <button
                    onClick={() => setIsEditing(true)}
                    className="edit-name-btn"
                    title="Редактировать имя"
                  >
                    <RiEditLine />
                  </button>
                </div>
              )}
            </div>

            <div className="info-group">
              <label>
                <RiChat3Line className="label-icon" />
                Количество чатов
              </label>
              <div className="info-value">
                {user?.chatCount || 0}
              </div>
            </div>
          </div>

          <div className="profile-actions">
            <button
              onClick={handleLogout}
              className="action-btn logout"
            >
              <RiLogoutBoxLine />
              Выйти
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default UserProfile;
