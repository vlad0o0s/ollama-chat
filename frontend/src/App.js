import React, { useState, useRef, useEffect } from 'react';
import './App.css';
import { useAuth } from './AuthContext';
import Login from './components/Login';
import Register from './components/Register';
import UserProfile from './components/UserProfile';
import AdminPanel from './components/AdminPanel';
import ChatManager from './components/ChatManager';
import MarkdownRenderer from './components/MarkdownRenderer';
import { 
  RiRobot2Line, 
  RiDeleteBin6Line, 
  RiSendPlaneFill, 
  RiSettings3Line, 
  RiLoader4Line, 
  RiAddLine, 
  RiSearchLine, 
  RiPushpinLine, 
  RiMenuLine, 
  RiCloseLine, 
  RiChat3Line, 
  RiMoreLine, 
  RiRefreshLine, 
  RiTimeLine,
  RiPauseFill,
  RiUserLine,
  RiFileCopyLine,
  RiCheckLine,
  RiImageLine,
  RiImageAddLine,
  RiDownloadLine,
  RiArrowDownSLine,
  RiArrowUpSLine,
  RiImage2Line,
  RiPencilLine,
  RiCheckLine as RiCheckLineIcon,
  RiCloseLine as RiCloseLineIcon
} from 'react-icons/ri';

function App() {
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [aiResponse, setAiResponse] = useState('');
  const [isStopping, setIsStopping] = useState(false);
  const [abortController, setAbortController] = useState(null);
  const [ollamaUrl, setOllamaUrl] = useState('http://192.168.10.12:11434');
  const [fallbackUrls, setFallbackUrls] = useState([
    'http://192.168.10.12:11434',
    'http://localhost:11434',
    'http://127.0.0.1:11434'
  ]);
  const [model, setModel] = useState('gpt-oss:20b');
  const [availableModels, setAvailableModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [chats, setChats] = useState([]);
  const [currentChatId, setCurrentChatId] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [useWebSearch, setUseWebSearch] = useState(false); // Выключен по умолчанию
  const [isSearching, setIsSearching] = useState(false);
  const [searchSources, setSearchSources] = useState([]);
  const [isImageMode, setIsImageMode] = useState(false); // Переключатель режима изображения
  const [imageAspectRatio, setImageAspectRatio] = useState('1:1'); // Соотношение сторон изображения
  const [imageGenerationStatus, setImageGenerationStatus] = useState(null); // Статус генерации изображения
  const [lightboxImage, setLightboxImage] = useState(null); // Изображение для лайтбокса
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [authMode, setAuthMode] = useState('login'); // 'login' или 'register'
  const [showProfile, setShowProfile] = useState(false);
  const [showAdminPanel, setShowAdminPanel] = useState(false);
  const [chatRefreshTrigger, setChatRefreshTrigger] = useState(0);
  const [titleUpdatedForChat, setTitleUpdatedForChat] = useState(new Set());
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [connectionCheckInterval, setConnectionCheckInterval] = useState(null);
  const [copiedMessages, setCopiedMessages] = useState(new Set());
  const [showPlusMenu, setShowPlusMenu] = useState(false);
  const [imageForCreation, setImageForCreation] = useState(null); // Загруженное изображение для создания
  const [editingMessageId, setEditingMessageId] = useState(null); // ID редактируемого сообщения
  const [editingContent, setEditingContent] = useState(''); // Содержимое редактируемого сообщения
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const plusMenuRef = useRef(null);
  const imageCreationFileInputRef = useRef(null); // For image creation specific upload

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Функция копирования текста в буфер обмена с поддержкой HTML
  const downloadImage = async (imageUrl, filename) => {
    try {
      const response = await fetch(imageUrl);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'image.png';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      console.error('Ошибка скачивания изображения:', err);
      // Fallback - открываем в новой вкладке
      window.open(imageUrl, '_blank');
    }
  };

  const copyToClipboard = async (text, messageIndex) => {
    try {
      // Проверяем, поддерживает ли браузер Clipboard API
      if (navigator.clipboard && window.ClipboardItem) {
        // Создаем HTML версию текста (убираем markdown разметку)
        const htmlText = text
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>')
          .replace(/`(.*?)`/g, '<code>$1</code>')
          .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
          .replace(/^# (.*$)/gm, '<h1>$1</h1>')
          .replace(/^## (.*$)/gm, '<h2>$1</h2>')
          .replace(/^### (.*$)/gm, '<h3>$1</h3>')
          .replace(/^#### (.*$)/gm, '<h4>$1</h4>')
          .replace(/^##### (.*$)/gm, '<h5>$1</h5>')
          .replace(/^###### (.*$)/gm, '<h6>$1</h6>')
          .replace(/^\* (.*$)/gm, '<li>$1</li>')
          .replace(/^- (.*$)/gm, '<li>$1</li>')
          .replace(/^\d+\. (.*$)/gm, '<li>$1</li>')
          .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')
          .replace(/\n/g, '<br>');

        // Создаем ClipboardItem с HTML и текстовой версией
        const clipboardItem = new ClipboardItem({
          'text/html': new Blob([htmlText], { type: 'text/html' }),
          'text/plain': new Blob([text], { type: 'text/plain' })
        });

        await navigator.clipboard.write([clipboardItem]);
      } else {
        // Fallback - копируем только текст
        await navigator.clipboard.writeText(text);
      }
      
      // Добавляем индекс сообщения в множество скопированных
      setCopiedMessages(prev => new Set([...prev, messageIndex]));
      
      // Убираем индикатор через 2 секунды
      setTimeout(() => {
        setCopiedMessages(prev => {
          const newSet = new Set(prev);
          newSet.delete(messageIndex);
          return newSet;
        });
      }, 2000);
      
      console.log('Текст скопирован в буфер обмена');
    } catch (err) {
      console.error('Ошибка копирования в буфер обмена:', err);
      // Fallback для старых браузеров
      try {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        
        setCopiedMessages(prev => new Set([...prev, messageIndex]));
        setTimeout(() => {
          setCopiedMessages(prev => {
            const newSet = new Set(prev);
            newSet.delete(messageIndex);
            return newSet;
          });
        }, 2000);
      } catch (fallbackErr) {
        console.error('Fallback копирование также не удалось:', fallbackErr);
      }
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Обработка ESC для закрытия лайтбокса
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && lightboxImage) {
        setLightboxImage(null);
      }
    };
    
    if (lightboxImage) {
      document.addEventListener('keydown', handleEscape);
      // Блокируем скролл страницы при открытом лайтбоксе
      document.body.style.overflow = 'hidden';
    }
    
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [lightboxImage]);

  // Функция для генерации возможных IP адресов
  const generatePossibleUrls = () => {
    const urls = [
      // Сначала пробуем ваш основной IP для разработки
      'http://192.168.10.12:11434',
      // Потом localhost для переноса на другой ПК
      'http://localhost:11434',
      'http://127.0.0.1:11434'
    ];
    
    // Добавляем возможные локальные IP адреса для других сетей
    const possibleIPs = [
      '192.168.1.1', '192.168.1.2', '192.168.1.3', '192.168.1.4', '192.168.1.5',
      '192.168.0.1', '192.168.0.2', '192.168.0.3', '192.168.0.4', '192.168.0.5',
      '192.168.10.1', '192.168.10.2', '192.168.10.3', '192.168.10.4', '192.168.10.5',
      '10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4', '10.0.0.5',
      '172.16.0.1', '172.16.0.2', '172.16.0.3', '172.16.0.4', '172.16.0.5'
    ];
    
    possibleIPs.forEach(ip => {
      urls.push(`http://${ip}:11434`);
    });
    
    return urls;
  };

  // Загрузка доступных моделей из Ollama
  const loadAvailableModels = async () => {
    if (loadingModels) {
      return;
    }
    
    setLoadingModels(true);
    
    try {
      const startTime = Date.now();
      
      const response = await fetch(`${ollamaUrl}/api/tags`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        }
      });
      
      const endTime = Date.now();
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      const models = data.models || [];
      
      
      setAvailableModels(models);
      
      // Если текущая модель не найдена в списке, выбираем первую доступную
      const currentModelExists = models.some(m => m.name === model);
      if (!currentModelExists && models.length > 0) {
        setModel(models[0].name);
      }
      
      setIsConnected(true);
    } catch (error) {
      
      setAvailableModels([]);
      setIsConnected(false);
    } finally {
      setLoadingModels(false);
    }
  };

  // Функция для проверки соединения с Ollama с автоматическим fallback
  const checkOllamaConnection = async () => {
    // Сначала пробуем текущий URL
    try {
      const response = await fetch(`${ollamaUrl}/api/tags`, {
        method: 'GET',
        mode: 'cors',
        timeout: 2000,
        headers: {
          'Content-Type': 'application/json',
        }
      });
      
      if (response.ok) {
        setIsConnected(true);
        return true;
      }
    } catch (error) {
      console.log('App: Текущий URL недоступен, пробуем fallback URLs');
    }

    // Если текущий URL не работает, пробуем fallback URLs
    const allPossibleUrls = generatePossibleUrls();
    console.log(`App: Пробуем ${allPossibleUrls.length} возможных URL для подключения к Ollama`);
    
    for (const url of allPossibleUrls) {
      if (url === ollamaUrl) continue; // Пропускаем уже проверенный URL
      
      try {
        console.log(`App: Пробуем подключиться к ${url}`);
        const response = await fetch(`${url}/api/tags`, {
          method: 'GET',
          mode: 'cors',
          timeout: 2000,
          headers: {
            'Content-Type': 'application/json',
          }
        });
        
        if (response.ok) {
          console.log(`App: ✅ Успешное подключение к ${url}`);
          setOllamaUrl(url); // Обновляем URL на рабочий
          setIsConnected(true);
          return true;
        }
      } catch (error) {
        // Логируем только важные URL для отладки
        if (url.includes('192.168.10.12') || url.includes('localhost') || url.includes('127.0.0.1')) {
          console.log(`App: ${url} недоступен:`, error.message);
        }
      }
    }

    // Если ни один URL не работает
    console.error('App: ❌ Все URL недоступны. Убедитесь что Ollama запущен с поддержкой CORS');
    setIsConnected(false);
    return false;
  };

  // Загружаем модели при первом запуске
  useEffect(() => {
    if (initialized) return; // Предотвращаем повторную инициализацию
    
    const initializeApp = async () => {
      
      setInitialized(true);
      await loadAvailableModels();
      
      // Запускаем периодическую проверку соединения каждые 30 секунд
      const interval = setInterval(checkOllamaConnection, 30000);
      setConnectionCheckInterval(interval);
      
      // Небольшая задержка для обновления состояния
      setTimeout(() => {
      }, 100);
    };
    initializeApp();

    // Очистка интервала при размонтировании
    return () => {
      if (connectionCheckInterval) {
        clearInterval(connectionCheckInterval);
      }
    };
  }, [initialized]);

  // Загрузка чатов из базы данных
  const loadChats = async () => {
    if (!isAuthenticated) return;
    
    try {
      const token = localStorage.getItem('token');
      const response = await fetch('/api/chats', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const chatsData = await response.json();
        setChats(chatsData);
        
        // Если нет текущего чата, выбираем первый
        if (!currentChatId && chatsData.length > 0) {
          setCurrentChatId(chatsData[0].id);
          await loadChatMessages(chatsData[0].id);
        }
      }
    } catch (error) {
    }
  };

  // Загрузка сообщений чата
  const loadChatMessages = async (chatId) => {
    if (!chatId) return;
    
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/chats/${chatId}`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const chatData = await response.json();
        setMessages(chatData.messages || []);
      }
    } catch (error) {
    }
  };

  // Загрузка чатов при аутентификации
  useEffect(() => {
    if (isAuthenticated) {
      loadChats();
    } else {
      setChats([]);
      setCurrentChatId(null);
      setMessages([]);
    }
  }, [isAuthenticated]);

  // Функция для выбора чата
  const handleChatSelect = async (chatId) => {
    console.log('App: Выбор чата:', chatId, 'Предыдущий чат:', currentChatId);
    
    // Очищаем флаг обновления названия только при смене на другой чат
    if (currentChatId !== chatId) {
      console.log('App: Смена чата, очищаем флаг обновления названия');
      setTitleUpdatedForChat(new Set());
    }
    
    setCurrentChatId(chatId);
    setAiResponse(''); // Очищаем ответ ИИ при смене чата
    if (chatId) {
      await loadChatMessages(chatId);
    } else {
      setMessages([]);
    }
  };


  const stopGeneration = () => {
    if (abortController) {
      abortController.abort();
      setIsStopping(true);
      
      // Фокусируемся на поле ввода после остановки генерации
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    }
  };

  const sendMessage = async (retryCount = 0) => {
    if (!inputMessage.trim() || isLoading) return;
    
    // Если включен режим изображения, используем генерацию изображения
    if (isImageMode) {
      await generateImage();
      return;
    }

    // Проверяем соединение с Ollama перед отправкой
    const isConnected = await checkOllamaConnection();
    if (!isConnected) {
      console.error('App: Нет соединения с Ollama, отменяем отправку сообщения');
      const errorMessage = { 
        role: 'assistant', 
        content: 'Нет соединения с Ollama. Проверьте, что Ollama запущен и доступен.'
      };
      const finalMessages = [...messages, errorMessage];
      setMessages(finalMessages);
      return;
    }

    // Создаем новый чат только если его нет и есть сообщение для отправки
    let chatId = currentChatId;
    if (!chatId) {
      console.log('App: Нет выбранного чата, создаем новый');
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

        console.log('App: Получен ответ от сервера при создании чата:', response.status);

        if (response.ok) {
          const newChat = await response.json();
          console.log('App: Новый чат создан:', newChat);
          chatId = newChat.id;
          setCurrentChatId(chatId);
          // Перезагружаем список чатов, чтобы получить актуальное состояние
          console.log('App: Перезагружаем список чатов');
          await loadChats();
        } else {
          console.error('App: Ошибка создания чата, статус:', response.status);
          return;
        }
      } catch (error) {
        console.error('App: Ошибка создания чата:', error);
        return;
      }
    } else {
      console.log('App: Используем существующий чат:', chatId);
    }

    const userMessage = { role: 'user', content: inputMessage };
    const newMessages = [...messages, userMessage];
    const isFirstUserMessage = messages.length === 0; // Проверяем ДО добавления сообщения
    console.log('App: Отправка сообщения. Текущее количество сообщений:', messages.length, 'Первое сообщение:', isFirstUserMessage);
    setMessages(newMessages);
    setInputMessage('');
    resetTextareaHeight(); // Сбрасываем высоту textarea к исходному состоянию
    setIsLoading(true);
    setAiResponse(''); // Очищаем предыдущий ответ
    setIsStopping(false);
    
    // Фокусируемся на поле ввода для продолжения диалога
    setTimeout(() => {
      inputRef.current?.focus();
    }, 50);
    
    // Создаем AbortController для возможности остановки
    const controller = new AbortController();
    setAbortController(controller);

    // Обновляем чат с новым сообщением (без обновления last_message)
    setChats(prev => prev.map(chat => {
      if (chat.id === chatId) {
        return { 
          ...chat, 
          messages: newMessages
        };
      }
      return chat;
    }));

    try {
      // Обновляем название чата в реальном времени, если это первое сообщение пользователя
      console.log('App: Проверка условий обновления названия:', {
        isFirstUserMessage,
        chatId,
        titleUpdatedForChat: Array.from(titleUpdatedForChat),
        hasInSet: titleUpdatedForChat.has(chatId)
      });
      
      if (isFirstUserMessage && !titleUpdatedForChat.has(chatId)) {
        const currentChat = chats.find(chat => chat.id === chatId);
        console.log('App: Найден чат для обновления:', currentChat);
        console.log('App: Все чаты в App.js:', chats);
        
        // Если чат не найден в локальном массиве, создаем временный объект чата
        const chatToUpdate = currentChat || { id: chatId, title: 'Новый чат' };
        
        if (chatToUpdate) {
          const newTitle = generateChatTitle(inputMessage);
          console.log('App: Обновляем название чата в реальном времени с', chatToUpdate.title, 'на', newTitle);
          
          // Отмечаем, что название для этого чата уже обновлено
          setTitleUpdatedForChat(prev => new Set(prev).add(chatId));
          
          // Обновляем название в локальном состоянии сразу
          setChats(prev => {
            const updatedChats = prev.map(chat => 
              chat.id === chatId ? { ...chat, title: newTitle } : chat
            );
            console.log('App: Обновленное состояние чатов (название):', updatedChats);
            return updatedChats;
          });
          
          // Обновляем название в базе данных асинхронно
          try {
            const token = localStorage.getItem('token');
            await fetch(`/api/chats/${chatId}`, {
              method: 'PUT',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
              },
              body: JSON.stringify({
                title: newTitle
              })
            });
            
            // Перезагружаем список чатов для обновления в ChatManager
            await loadChats();
            setChatRefreshTrigger(prev => prev + 1);
          } catch (error) {
            console.error('Ошибка обновления названия чата:', error);
          }
        }
      }
      
      const startTime = Date.now();
      
      // Используем поиск, если включен
      let response;
      if (useWebSearch) {
        setIsSearching(true);
        setSearchSources([]);
        
        const token = localStorage.getItem('token');
        response = await fetch('/api/chat/search', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            message: inputMessage,
            chat_id: chatId,
            use_search: true
          }),
          signal: controller.signal
        });
      } else {
        // Используем прямой запрос к Ollama (старый способ)
        // Фильтруем удаленные сообщения и формируем массив для Ollama
        const messagesForOllama = newMessages
          .filter(msg => !msg.deleted && msg.role && msg.content)
          .map(msg => ({
            role: msg.role,
            content: msg.content
          }));
        
        response = await fetch(`${ollamaUrl}/api/chat`, {
        method: 'POST',
        mode: 'cors',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: model,
          messages: messagesForOllama,
          stream: true
        }),
        signal: controller.signal,
          timeout: 300000
      });
      }

      const endTime = Date.now();
      const responseTime = endTime - startTime;
      

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      let fullResponse = '';
      let chunkCount = 0;
      let lastChunkTime = Date.now();

      // Обработка потокового ответа
      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      console.log('App: Начинаем чтение потокового ответа');

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log('App: Поток завершен, получено чанков:', chunkCount);
          break;
        }

        chunkCount++;
        lastChunkTime = Date.now();
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (!line.trim()) continue;
          
          // Обработка Server-Sent Events (SSE) формата
          if (line.startsWith('data: ')) {
            try {
              const jsonStr = line.substring(6); // Убираем "data: "
              const data = JSON.parse(jsonStr);
              
              // Обработка контента
              if (data.content) {
                fullResponse += data.content;
                setAiResponse(fullResponse);
              }
              
              // Обработка метаданных поиска
              if (data.search_metadata) {
                setIsSearching(false);
                if (data.search_metadata.sources && data.search_metadata.sources.length > 0) {
                  setSearchSources(data.search_metadata.sources);
                }
              }
              
              // Завершение
              if (data.done) {
                console.log('App: Получен флаг done');
                break;
              }
              
              // Ошибки
              if (data.error) {
                console.error('App: Ошибка в ответе:', data.error);
                throw new Error(data.error);
              }
            } catch (e) {
              console.error('App: Ошибка парсинга JSON:', line, e);
            }
          } else if (useWebSearch === false) {
            // Старый формат Ollama (NDJSON) - только если поиск выключен
            try {
              const data = JSON.parse(line);
              
              if (data.message && data.message.content) {
                fullResponse += data.message.content;
                setAiResponse(fullResponse);
              }
              
              if (data.done) {
                break;
              }

              if (data.error) {
                throw new Error(`Ollama error: ${data.error}`);
              }
            } catch (e) {
              console.error('App: Ошибка парсинга JSON строки:', line, e);
            }
          }
        }

        // Проверяем таймаут между чанками
        if (Date.now() - lastChunkTime > 30000) {
          console.error('App: Таймаут при чтении потока');
          throw new Error('Timeout: No data received for 30 seconds');
        }
      }
      
      setIsSearching(false);

      console.log(`App: Завершено чтение потока. Итоговый ответ: ${fullResponse.length} символов`);

      // Проверяем, что получили непустой ответ
      if (!fullResponse.trim()) {
        console.error('App: Получен пустой ответ');
        throw new Error('Empty response');
      }

      // Останавливаем загрузку и сбрасываем счетчик попыток
      setIsLoading(false);
      setRetryAttempt(0);
      
      // Фокусируемся на поле ввода для продолжения диалога
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
      
      // Добавляем финальное сообщение в массив
      // Сообщения уже сохранены в БД бэкендом
      if (!isStopping) {
        const assistantMessage = { 
          role: 'assistant', 
          content: fullResponse,
          sources: searchSources.length > 0 ? searchSources : undefined
        };
        const finalMessages = [...newMessages, assistantMessage];
        
        // Добавляем сообщение в массив
        setMessages(finalMessages);
        
        // Обновляем чат с ответом и последним сообщением
        setChats(prev => prev.map(chat => {
          if (chat.id === chatId) {
            const lastMessageText = truncateMessage(fullResponse);
            return { 
              ...chat, 
              messages: finalMessages,
              last_message: lastMessageText,
              last_message_at: new Date().toISOString()
            };
          }
          return chat;
        }));
      } else {
        // Если была остановка, добавляем частичный ответ
        if (fullResponse.trim()) {
          const assistantMessage = { 
            role: 'assistant', 
            content: fullResponse + '\n\n[Генерация остановлена пользователем]',
            sources: searchSources.length > 0 ? searchSources : undefined
          };
          const finalMessages = [...newMessages, assistantMessage];
          
          // Добавляем сообщение в массив
          setMessages(finalMessages);
          
          setChats(prev => prev.map(chat => {
            if (chat.id === chatId) {
              const lastMessageText = truncateMessage(fullResponse + '\n\n[Генерация остановлена пользователем]');
              return { 
                ...chat, 
                messages: finalMessages,
                last_message: lastMessageText,
                last_message_at: new Date().toISOString()
              };
            }
            return chat;
          }));
        }
      }
      
      // Очищаем источники для следующего запроса
      setSearchSources([]);
      
      // Очищаем временный ответ ИИ, так как он теперь в массиве messages
      setAiResponse('');
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log('App: Запрос был отменен пользователем');
        return;
      }
      
      console.error('App: Ошибка при отправке сообщения:', error);
      
      let errorMessageText = 'Извините, произошла ошибка при подключении к Ollama.';
      
      // Более детальная обработка ошибок
      if (error.message.includes('Empty response from Ollama')) {
        errorMessageText = 'Получен пустой ответ от ИИ. Возможно, модель перегружена или произошла ошибка.';
        
        // Попробуем повторить запрос для пустого ответа
        if (retryCount < 2) {
          console.log(`App: Повторная попытка ${retryCount + 1}/2 для пустого ответа`);
          setRetryAttempt(retryCount + 1);
          setTimeout(() => {
            sendMessage(retryCount + 1);
          }, 2000 * (retryCount + 1)); // Увеличиваем задержку с каждой попыткой
          return;
        }
        errorMessageText += ' Попробуйте еще раз.';
      } else if (error.message.includes('Timeout')) {
        errorMessageText = 'Превышено время ожидания ответа от ИИ.';
        
        // Попробуем повторить запрос для таймаута
        if (retryCount < 1) {
          console.log(`App: Повторная попытка ${retryCount + 1}/1 для таймаута`);
          setRetryAttempt(retryCount + 1);
          setTimeout(() => {
            sendMessage(retryCount + 1);
          }, 3000);
          return;
        }
        errorMessageText += ' Попробуйте еще раз или проверьте подключение.';
      } else if (error.message.includes('Ollama error')) {
        errorMessageText = `Ошибка Ollama: ${error.message.replace('Ollama error: ', '')}`;
      } else if (error.name === 'TypeError' && error.message.includes('fetch')) {
        errorMessageText = 'Ошибка подключения к Ollama. Проверьте, что Ollama запущен и доступен по указанному адресу.';
      } else if (error.message.includes('HTTP error')) {
        const status = error.message.match(/status: (\d+)/)?.[1];
        
        if (status === '400') {
          errorMessageText = 'Некорректный запрос к Ollama. Проверьте настройки модели.';
        } else if (status === '404') {
          errorMessageText = 'Модель не найдена в Ollama. Проверьте название модели.';
        } else if (status === '500') {
          errorMessageText = 'Внутренняя ошибка Ollama. Попробуйте перезапустить Ollama.';
        } else {
          errorMessageText = `Ошибка HTTP ${status} при обращении к Ollama.`;
        }
      }
      
      console.error('App: Показываем пользователю ошибку:', errorMessageText);
      
      setIsLoading(false);
      
      // Фокусируемся на поле ввода после ошибки
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
      
      const errorMessage = { 
        role: 'assistant', 
        content: errorMessageText
      };
      const finalMessages = [...newMessages, errorMessage];
      
      // Добавляем сообщение об ошибке в массив
      setMessages(finalMessages);
      
      setChats(prev => prev.map(chat => {
        if (chat.id === currentChatId) {
          const lastMessageText = truncateMessage(errorMessageText);
          return { 
            ...chat, 
            messages: finalMessages,
            last_message: lastMessageText,
            last_message_at: new Date().toISOString()
          };
        }
        return chat;
      }));
      
      // Очищаем временный ответ ИИ, так как он теперь в массиве messages
      setAiResponse('');
    } finally {
      setIsStopping(false);
      setAbortController(null);
      
      // Убеждаемся, что поле ввода остается активным
      setTimeout(() => {
        if (!isLoading) {
          inputRef.current?.focus();
        }
      }, 200);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleInputChange = (e) => {
    setInputMessage(e.target.value);
    // Автоматическое расширение textarea
    const textarea = e.target;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
  };

  // Обработчик выбора файла для создания изображения
  const handleFileSelectForCreation = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.startsWith('image/')) {
        alert('Пожалуйста, выберите файл изображения');
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        alert('Файл слишком большой. Максимальный размер: 10MB');
        return;
      }
      const reader = new FileReader();
      reader.onload = (event) => {
        setImageForCreation({
          file: file,
          url: event.target.result,
          name: file.name
        });
      };
      reader.readAsDataURL(file);
    }
    // Сбрасываем значение input
    if (imageCreationFileInputRef.current) {
      imageCreationFileInputRef.current.value = '';
    }
  };

  // Обработчики меню "+"
  const handlePlusMenuToggle = () => {
    setShowPlusMenu(!showPlusMenu);
  };

  const handleMenuOptionClick = (option) => {
    setShowPlusMenu(false);
    
    switch(option) {
      case 'createImage':
        if (isImageMode) {
          // Если режим уже включен, выключаем его и очищаем изображение
          setIsImageMode(false);
          setImageForCreation(null);
        } else {
          // Отключаем поиск при включении режима создания изображения
          if (useWebSearch) {
            setUseWebSearch(false);
          }
          setIsImageMode(true);
          // Если есть последнее изображение пользователя в чате, используем его
          if (currentChatId && messages.length > 0) {
            const lastUserImage = [...messages].reverse().find(
              msg => msg.role === 'user' && msg.message_type === 'image' && msg.image_url
            );
            if (lastUserImage) {
              // Загружаем изображение из URL для превью
              fetch(lastUserImage.image_url)
                .then(res => res.blob())
                .then(blob => {
                  const reader = new FileReader();
                  reader.onload = (event) => {
                    setImageForCreation({
                      file: new File([blob], 'image.png', { type: blob.type }),
                      url: event.target.result,
                      name: 'image.png'
                    });
                  };
                  reader.readAsDataURL(blob);
                })
                .catch(err => console.error('Ошибка загрузки изображения:', err));
            }
          }
        }
        break;
      case 'webSearch':
        if (useWebSearch) {
          setUseWebSearch(false);
        } else {
          // Отключаем режим создания изображения при включении поиска
          if (isImageMode) {
            setIsImageMode(false);
            setImageForCreation(null);
          }
          setUseWebSearch(true);
        }
        break;
      default:
        break;
    }
  };

  // Закрытие меню при клике вне его
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (plusMenuRef.current && !plusMenuRef.current.contains(event.target)) {
        setShowPlusMenu(false);
      }
    };

    if (showPlusMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showPlusMenu]);

  // Удаление изображения для создания
  const handleRemoveImageForCreation = () => {
    setImageForCreation(null);
  };

  // Удаление сообщения
  const handleDeleteMessage = async (messageId) => {
    if (!currentChatId || !messageId) return;
    
    if (!window.confirm('Вы уверены, что хотите удалить это сообщение?')) {
      return;
    }

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/chats/${currentChatId}/messages/${messageId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        // Удаляем сообщение из локального состояния
        setMessages(prev => prev.filter(msg => msg.id !== messageId));
        // Перезагружаем сообщения из БД
        await loadChatMessages(currentChatId);
      } else {
        const error = await response.json();
        alert(error.detail || 'Ошибка удаления сообщения');
      }
    } catch (error) {
      console.error('Ошибка удаления сообщения:', error);
      alert('Ошибка сети при удалении сообщения');
    }
  };

  // Начало редактирования сообщения
  const handleStartEdit = (message) => {
    if (message.role !== 'user' || !message.id) return;
    setEditingMessageId(message.id);
    setEditingContent(message.content);
  };

  // Отмена редактирования
  const handleCancelEdit = () => {
    setEditingMessageId(null);
    setEditingContent('');
  };

  // Сохранение отредактированного сообщения
  const handleSaveEdit = async (messageId) => {
    if (!currentChatId || !messageId || !editingContent.trim()) return;

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/chats/${currentChatId}/messages/${messageId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          content: editingContent.trim()
        })
      });

      if (response.ok) {
        const updatedMessage = await response.json();
        // Обновляем сообщение в локальном состоянии
        setMessages(prev => prev.map(msg => 
          msg.id === messageId ? { ...msg, ...updatedMessage } : msg
        ));
        setEditingMessageId(null);
        setEditingContent('');
        // Перезагружаем сообщения из БД для получения актуальных данных
        await loadChatMessages(currentChatId);
      } else {
        const error = await response.json();
        alert(error.detail || 'Ошибка редактирования сообщения');
      }
    } catch (error) {
      console.error('Ошибка редактирования сообщения:', error);
      alert('Ошибка сети при редактировании сообщения');
    }
  };

  const generateImage = async () => {
    if (!inputMessage.trim() || isLoading) return;
    
    if (!currentChatId) {
      alert('Пожалуйста, выберите или создайте чат перед генерацией изображения');
      return;
    }

    setIsLoading(true);
    
    // Если есть изображение для создания, загружаем его на сервер вместе с описанием
    // Это создаст одно сообщение с изображением и текстом
    let referenceImageId = null;
    if (imageForCreation) {
      try {
        const token = localStorage.getItem('token');
        const formData = new FormData();
        formData.append('file', imageForCreation.file);
        formData.append('chat_id', currentChatId);
        // Добавляем описание в сообщение с изображением
        if (inputMessage.trim()) {
          formData.append('description', inputMessage.trim());
        }

        const uploadResponse = await fetch('/api/image/upload', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          },
          body: formData
        });

        if (uploadResponse.ok) {
          const uploadResult = await uploadResponse.json();
          referenceImageId = uploadResult.message_id;
          // Перезагружаем сообщения чтобы получить актуальные данные
          await loadChatMessages(currentChatId);
        } else {
          console.error('Ошибка загрузки изображения для создания');
        }
      } catch (error) {
        console.error('Ошибка при загрузке изображения:', error);
      }
    }
    
    // Вычисляем размеры изображения на основе выбранного соотношения сторон
    const getImageDimensions = (aspectRatio) => {
      const baseSize = 1024; // Базовый размер
      switch (aspectRatio) {
        case '9:16': // Вертикальное
          return { width: 576, height: 1024 };
        case '16:9': // Горизонтальное
          return { width: 1024, height: 576 };
        case '1:1': // Квадратное
          return { width: 1024, height: 1024 };
        case '3:4': // Портретное
          return { width: 768, height: 1024 };
        case '4:3': // Альбомное
          return { width: 1024, height: 768 };
        default:
          return { width: 1024, height: 1024 };
      }
    };

    const dimensions = getImageDimensions(imageAspectRatio);
    
    // Добавляем временное сообщение для отображения плейсхолдера
    const tempMessage = { 
      role: 'assistant', 
      content: '',
      message_type: 'image_generating',
      status: 'generating',
      aspect_ratio: imageAspectRatio,
      width: dimensions.width,
      height: dimensions.height
    };
      setMessages(prev => [...prev, tempMessage]);
    
    // Сбрасываем загруженное изображение после отправки запроса
    setImageForCreation(null);
    
    try {
      const token = localStorage.getItem('token');
      // Вычисляем размеры изображения на основе выбранного соотношения сторон
      const getImageDimensions = (aspectRatio) => {
        const baseSize = 1024; // Базовый размер
        switch (aspectRatio) {
          case '9:16': // Вертикальное
            return { width: 576, height: 1024 };
          case '16:9': // Горизонтальное
            return { width: 1024, height: 576 };
          case '1:1': // Квадратное
            return { width: 1024, height: 1024 };
          case '3:4': // Портретное
            return { width: 768, height: 1024 };
          case '4:3': // Альбомное
            return { width: 1024, height: 768 };
          default:
            return { width: 1024, height: 1024 };
        }
      };

      const dimensions = getImageDimensions(imageAspectRatio);

      const response = await fetch('/api/image/generate/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          chat_id: currentChatId,
          description: inputMessage.trim(),
          width: dimensions.width,
          height: dimensions.height,
          reference_image_id: referenceImageId || null
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              
              if (data.error) {
                setImageGenerationStatus({ stage: 'error', message: data.error });
                setMessages(prev => {
                  const updated = [...prev];
                  const lastIndex = updated.length - 1;
                  if (updated[lastIndex]?.message_type === 'image_generating') {
                    updated[lastIndex] = {
                      role: 'assistant',
                      content: `Ошибка: ${data.error}`,
                      message_type: 'text'
                    };
                  }
                  return updated;
                });
                break;
              }
              
              if (data.stage) {
                setImageGenerationStatus({ stage: data.stage, message: data.message });
                // Обновляем статус, но не меняем отображение (плейсхолдер остается)
                setMessages(prev => {
                  const updated = [...prev];
                  const lastIndex = updated.length - 1;
                  if (updated[lastIndex]?.message_type === 'image_generating') {
                    updated[lastIndex] = {
                      ...updated[lastIndex],
                      status: data.stage
                    };
                  }
                  return updated;
                });
              }
              
              if (data.done && data.success) {
                // Очищаем поле ввода
                setInputMessage('');
                
                // Перезагружаем сообщения чата для отображения нового изображения
                await loadChatMessages(currentChatId);
                
                // Прокручиваем вниз
                setTimeout(() => {
                  scrollToBottom();
                }, 100);
                
                setImageGenerationStatus(null);
              }
            } catch (e) {
              console.error('Ошибка парсинга SSE данных:', e);
            }
          }
        }
      }
      
    } catch (error) {
      console.error('Ошибка генерации изображения:', error);
      setImageGenerationStatus({ stage: 'error', message: error.message });
      setMessages(prev => {
        const updated = [...prev];
        const lastIndex = updated.length - 1;
        if (updated[lastIndex]?.message_type === 'image_generating') {
          updated[lastIndex] = {
            role: 'assistant',
            content: `Ошибка генерации изображения: ${error.message}`,
            message_type: 'text'
          };
        }
        return updated;
      });
    } finally {
      setIsLoading(false);
      setImageGenerationStatus(null);
      // Очищаем изображение для создания после генерации
      setImageForCreation(null);
    }
  };

  // Функция для сброса высоты textarea к исходному состоянию
  const resetTextareaHeight = () => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
  };

  const generateChatTitle = (firstMessage) => {
    // Убираем лишние пробелы и переносы строк
    const cleanMessage = firstMessage.trim().replace(/\s+/g, ' ');
    
    // Убираем знаки препинания в конце
    const trimmedMessage = cleanMessage.replace(/[.!?]+$/, '');
    
    // Если сообщение короткое, используем его полностью
    if (trimmedMessage.length <= 20) {
      return trimmedMessage;
    }
    
    // Ищем подходящее место для обрезки (конец слова)
    let title = trimmedMessage.slice(0, 20);
    const lastSpace = title.lastIndexOf(' ');
    
    // Если есть подходящее место для обрезки по пробелу (в пределах 70% от максимальной длины)
    if (lastSpace > 20 * 0.7) {
      title = title.slice(0, lastSpace);
    }
    
    return title + '...';
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



  // Показываем экран загрузки пока проверяется авторизация
  if (authLoading) {
    return (
      <div className="loading-screen">
        <div className="skeleton-loading-content">
          <div className="skeleton-loading-icon"></div>
          <div className="skeleton-loading-text"></div>
        </div>
      </div>
    );
  }

  // Показываем экран авторизации если пользователь не авторизован
  if (!isAuthenticated) {
    return (
      <div className="app">
        {authMode === 'login' ? (
          <Login onSwitchToRegister={() => setAuthMode('register')} />
        ) : (
          <Register onSwitchToLogin={() => setAuthMode('login')} />
        )}
      </div>
    );
  }

  // Показываем профиль пользователя если открыт
  if (showProfile) {
    return (
      <div className="app">
        <UserProfile onClose={() => setShowProfile(false)} />
      </div>
    );
  }

  // Показываем админ-панель если открыта
  if (showAdminPanel) {
    return (
      <div className="app">
        <AdminPanel onClose={() => setShowAdminPanel(false)} />
      </div>
    );
  }

  return (
    <div className="app">
      {/* Боковая панель с менеджером чатов */}
      <ChatManager 
        onChatSelect={handleChatSelect}
        currentChatId={currentChatId}
        refreshTrigger={chatRefreshTrigger}
        chats={chats}
        isHidden={!sidebarOpen}
      />

      <div className={`chat-container ${!sidebarOpen ? 'expanded' : ''}`}>
        <div className="chat-header">
          <div className="header-left">
            <button 
              onClick={() => setSidebarOpen(!sidebarOpen)} 
              className="menu-btn"
            >
              {sidebarOpen ? <RiCloseLine /> : <RiMenuLine />}
            </button>
            <h1>
              <RiRobot2Line className="header-icon" />
              Ollama Chat
              <span className="beta-badge">BETA</span>
            </h1>
          </div>
          
          <div className="header-right">
            <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`} title={`Подключение: ${ollamaUrl}`}>
              <div className="status-dot"></div>
            </div>
            {user?.role === 'admin' && (
              <button 
                onClick={() => setShowAdminPanel(true)} 
                className="admin-btn"
                title="Панель администратора"
              >
                <RiSettings3Line />
              </button>
            )}
            <button 
              onClick={() => setShowProfile(true)} 
              className="profile-btn"
              title={`${user?.name || 'Пользователь'}`}
            >
              <RiUserLine />
            </button>
            <button 
              onClick={() => setShowSettings(!showSettings)} 
              className="settings-btn"
            >
              <RiSettings3Line />
            </button>
          </div>
        </div>

        <div className={`settings-panel ${!showSettings ? 'hidden' : ''}`}>
          <div className="input-group">
            <RiRobot2Line className="input-icon" />
            {loadingModels ? (
              <div className="skeleton-select"></div>
            ) : (
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="model-select"
              >
                {availableModels.length > 0 ? (
                  availableModels.map((modelOption) => (
                    <option key={modelOption.name} value={modelOption.name}>
                      {modelOption.name} ({Math.round(modelOption.size / 1024 / 1024 / 1024 * 100) / 100} GB)
                    </option>
                  ))
                ) : (
                  <option value="">Нет доступных моделей</option>
                )}
              </select>
            )}
            {loadingModels ? (
              <div className="skeleton-refresh-btn"></div>
            ) : (
              <button 
                onClick={loadAvailableModels} 
                className="refresh-models-btn"
                title="Обновить список моделей"
              >
                <RiRefreshLine />
              </button>
            )}
          </div>
        </div>

        <div className="messages-container">
          {messages.length === 0 && (
            <div className="welcome-message">
              <h2>Добро пожаловать в Ollama Chat!</h2>
              <p>Начните общение, отправив сообщение ниже.</p>
              <div className="beta-info">
                <p>🚀 <strong>Первая бета версия</strong> - тестируйте и сообщайте об ошибках!</p>
              </div>
              {availableModels.length > 0 && (
                <p>Доступно моделей: {availableModels.length}</p>
              )}
            </div>
          )}
          
          {[...messages, ...(isLoading || aiResponse ? [{
            role: 'assistant',
            content: isLoading ? 'typing' : aiResponse,
            isTyping: isLoading,
            retryAttempt: retryAttempt
          }] : [])].map((message, index) => (
            <div key={index} className={`message ${message.role}`}>
              {message.role === 'user' ? (
                <div className="message-wrapper-user">
                  {editingMessageId === message.id ? (
                    <div className="message-edit-container">
                      <textarea
                        className="message-edit-textarea"
                        value={editingContent}
                        onChange={(e) => setEditingContent(e.target.value)}
                        autoFocus
                        rows={3}
                      />
                      <div className="message-edit-actions">
                        <button
                          className="message-edit-save"
                          onClick={() => handleSaveEdit(message.id)}
                          title="Сохранить"
                        >
                          <RiCheckLineIcon />
                        </button>
                        <button
                          className="message-edit-cancel"
                          onClick={handleCancelEdit}
                          title="Отменить"
                        >
                          <RiCloseLineIcon />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {message.message_type === 'image' && message.image_url ? (
                        <div className="message-content user-image-message">
                          <div className="user-image-preview-container">
                            <img 
                              src={message.image_url} 
                              alt={message.content || "Загруженное изображение"}
                              className="user-uploaded-image"
                              loading="lazy"
                              onClick={() => setLightboxImage(message.image_url)}
                            />
                          </div>
                          {message.content && message.content.trim() && (
                            <div className="message-text">
                              <MarkdownRenderer content={message.content} />
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="message-content">
                          <MarkdownRenderer content={message.content} />
                          {message.edited && (
                            <span className="message-edited-indicator" title={`Отредактировано ${message.edited_at ? new Date(message.edited_at).toLocaleString('ru-RU') : ''}`}>
                              (изменено)
                            </span>
                          )}
                        </div>
                      )}
                      {message.id && (
                        <div className="message-actions">
                          <button
                            className="message-action-button message-edit-button"
                            onClick={() => handleStartEdit(message)}
                            title="Редактировать"
                          >
                            <RiPencilLine />
                          </button>
                          <button
                            className="message-action-button message-delete-button"
                            onClick={() => handleDeleteMessage(message.id)}
                            title="Удалить"
                          >
                            <RiDeleteBin6Line />
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              ) : message.role === 'assistant' ? (
                message.isTyping ? (
                  <div className="typing-indicator">
                    <div className="glass-typing-dots">
                      <div className="glass-typing-dot"></div>
                      <div className="glass-typing-dot"></div>
                      <div className="glass-typing-dot"></div>
                    </div>
                    <span className="typing-text">
                      Генерируется ответ...
                      {message.retryAttempt > 0 && (
                        <span className="retry-indicator">
                          (Попытка {message.retryAttempt})
                        </span>
                      )}
                    </span>
                  </div>
                ) : message.message_type === 'image_generating' ? (
                  <div className="message-content image-message">
                    <div className="image-preview-container">
                      <div 
                        className="image-generating-placeholder"
                        style={{
                          aspectRatio: message.aspect_ratio ? message.aspect_ratio.replace(':', '/') : '1/1',
                          maxWidth: message.width ? `${Math.min(message.width, 1024)}px` : '1024px',
                          maxHeight: message.height ? `${Math.min(message.height, 1024)}px` : '1024px'
                        }}
                      >
                        <div className="generating-image-blur">
                          <div className="generating-noise"></div>
                        </div>
                        {message.status === 'error' && (
                          <div className="generating-error-overlay">
                            <div className="generating-error-text">Ошибка генерации</div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : message.message_type === 'image' && message.image_url ? (
                  <div className="message-content image-message">
                    <div className="image-preview-container">
                      <img 
                        src={message.image_url} 
                        alt={message.content || "Сгенерированное изображение"}
                        className="generated-image"
                        loading="lazy"
                        onClick={() => setLightboxImage(message.image_url)}
                      />
                      <div className="image-actions">
                        <button
                          className="image-action-button download-image-button"
                          onClick={(e) => {
                            e.stopPropagation();
                            downloadImage(message.image_url, message.image_metadata?.filename || 'image.png');
                          }}
                          title="Скачать изображение"
                        >
                          <RiDownloadLine className="action-icon" />
                        </button>
                      </div>
                      {message.image_metadata && (
                        <div className="image-metadata">
                          <details className="image-prompt-details">
                            <summary>
                              <span>Промпты</span>
                              <RiArrowDownSLine className="details-icon" />
                            </summary>
                            <div className="prompt-info">
                              <div className="prompt-section">
                                <strong>Positive:</strong>
                                <p>{message.image_metadata.prompt_positive || 'N/A'}</p>
                              </div>
                              <div className="prompt-section">
                                <strong>Negative:</strong>
                                <p>{message.image_metadata.prompt_negative || 'N/A'}</p>
                              </div>
                            </div>
                          </details>
                        </div>
                      )}
                    </div>
                    {message.content && message.content.trim() && (
                      <div className="message-text">
                        <MarkdownRenderer content={message.content} />
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="message-content">
                      <MarkdownRenderer content={message.content} />
                    </div>
                    {message.sources && message.sources.length > 0 && (
                      <div className="sources-container">
                        <div className="sources-header">
                          <RiSearchLine style={{fontSize: '14px', marginRight: '6px'}} />
                          <span>Источники</span>
                        </div>
                        <div className="sources-list">
                          {message.sources.map((source, idx) => {
                            try {
                              const url = new URL(source);
                              const domain = url.hostname.replace('www.', '');
                              return (
                                <a
                                  key={idx}
                                  href={source}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="source-link"
                                  title={source}
                                >
                                  {domain}
                                </a>
                              );
                            } catch {
                              return (
                                <a
                                  key={idx}
                                  href={source}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="source-link"
                                  title={source}
                                >
                                  {source.length > 40 ? source.substring(0, 40) + '...' : source}
                                </a>
                              );
                            }
                          })}
                        </div>
                      </div>
                    )}
                    <button
                      className="copy-button"
                      onClick={() => copyToClipboard(message.content, index)}
                      title="Копировать ответ"
                    >
                      {copiedMessages.has(index) ? (
                        <RiCheckLine className="copy-icon copied" />
                      ) : (
                        <RiFileCopyLine className="copy-icon" />
                      )}
                    </button>
                  </>
                )
              ) : (
                <div className="message-content">
                  {message.content}
                </div>
              )}
            </div>
          ))}
          
          <div ref={messagesEndRef} />
        </div>

        {/* Кнопки активных режимов */}
        <div className="active-modes-buttons">
          {isImageMode && (
            <button
              onClick={() => {
                setIsImageMode(false);
                setImageForCreation(null);
              }}
              className="active-mode-button image-mode-button"
              title="Отключить режим создания изображения"
            >
              <RiImage2Line className="active-mode-button-icon" />
              <span>Создание изображения</span>
              <RiCloseLine className="active-mode-button-close" />
            </button>
          )}
          {useWebSearch && (
            <button
              onClick={() => setUseWebSearch(false)}
              className="active-mode-button search-mode-button"
              title="Отключить поиск в интернете"
            >
              <RiSearchLine className="active-mode-button-icon" />
              <span>Поиск в интернете</span>
              <RiCloseLine className="active-mode-button-close" />
            </button>
          )}
        </div>

        {isImageMode && (
          <div className="image-creation-interface">
            <div className="image-creation-content-compact">
              {imageForCreation ? (
                <div className="image-preview-wrapper-compact">
                  <div className="image-preview-container-compact">
                    <img 
                      src={imageForCreation.url} 
                      alt={imageForCreation.name}
                      className="image-preview-compact"
                    />
                    <button
                      className="image-preview-remove-compact"
                      onClick={handleRemoveImageForCreation}
                      title="Удалить изображение"
                    >
                      <RiCloseLine />
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => imageCreationFileInputRef.current?.click()}
                  className="image-upload-button-compact"
                  title="Добавить изображение"
                >
                  <RiAddLine className="image-upload-icon-compact" />
                  <RiImage2Line className="image-upload-icon-secondary-compact" />
                  <span className="image-upload-text-compact">Изображение</span>
                </button>
              )}
              {!imageForCreation && (
                <div className="aspect-ratio-selector-compact">
                  <div className="aspect-ratio-buttons-compact">
                    <button
                      onClick={() => setImageAspectRatio('9:16')}
                      className={`aspect-ratio-button-compact ${imageAspectRatio === '9:16' ? 'active' : ''}`}
                      title="Вертикальное (9:16)"
                    >
                      9:16
                    </button>
                    <button
                      onClick={() => setImageAspectRatio('16:9')}
                      className={`aspect-ratio-button-compact ${imageAspectRatio === '16:9' ? 'active' : ''}`}
                      title="Горизонтальное (16:9)"
                    >
                      16:9
                    </button>
                    <button
                      onClick={() => setImageAspectRatio('1:1')}
                      className={`aspect-ratio-button-compact ${imageAspectRatio === '1:1' ? 'active' : ''}`}
                      title="Квадратное (1:1)"
                    >
                      1:1
                    </button>
                    <button
                      onClick={() => setImageAspectRatio('3:4')}
                      className={`aspect-ratio-button-compact ${imageAspectRatio === '3:4' ? 'active' : ''}`}
                      title="Портретное (3:4)"
                    >
                      3:4
                    </button>
                    <button
                      onClick={() => setImageAspectRatio('4:3')}
                      className={`aspect-ratio-button-compact ${imageAspectRatio === '4:3' ? 'active' : ''}`}
                      title="Альбомное (4:3)"
                    >
                      4:3
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="input-container">
          <input
            ref={imageCreationFileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileSelectForCreation}
            style={{ display: 'none' }}
          />
          <div className="plus-menu-wrapper" ref={plusMenuRef}>
            <button
              onClick={handlePlusMenuToggle}
              disabled={isLoading}
              className="plus-menu-button"
              title="Дополнительные опции"
            >
              <RiAddLine style={{fontSize: '20px'}} />
            </button>
            {showPlusMenu && (
              <div className="plus-menu">
                <button
                  onClick={() => handleMenuOptionClick('createImage')}
                  className={`plus-menu-item ${isImageMode ? 'active' : ''}`}
                >
                  <RiImage2Line className="plus-menu-icon" />
                  <span>Создать изображение</span>
                </button>
                <button
                  onClick={() => handleMenuOptionClick('webSearch')}
                  className={`plus-menu-item ${useWebSearch ? 'active' : ''}`}
                >
                  <RiSearchLine className="plus-menu-icon" />
                  <span>Поиск в интернете</span>
                </button>
              </div>
            )}
          </div>
          <textarea
            ref={inputRef}
            value={inputMessage}
            onChange={handleInputChange}
            onKeyPress={handleKeyPress}
            placeholder="Введите ваше сообщение... (или перетащите изображение сюда)"
            className="message-input"
            rows="1"
            disabled={isLoading}
          />
          <button 
            onClick={isLoading ? stopGeneration : sendMessage} 
            className="send-button"
            disabled={!isLoading && (!inputMessage.trim() || isLoading)}
          >
            {isLoading ? (
              <div className="glass-loading-icon" style={{width: '20px', height: '20px', border: '2px solid rgba(255, 255, 255, 0.3)', borderTop: '2px solid #ffffff'}}></div>
            ) : (
              <RiSendPlaneFill className="send-icon" />
            )}
          </button>
        </div>
      </div>
      
      {/* Лайтбокс для просмотра изображений */}
      {lightboxImage && (
        <div 
          className="lightbox-overlay"
          onClick={() => setLightboxImage(null)}
        >
          <div 
            className="lightbox-content"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="lightbox-close"
              onClick={() => setLightboxImage(null)}
              title="Закрыть"
            >
              <RiCloseLine className="lightbox-close-icon" />
            </button>
            <img 
              src={lightboxImage} 
              alt="Просмотр изображения"
              className="lightbox-image"
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
