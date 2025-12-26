import React, { useState, memo, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import 'highlight.js/styles/github.css'; // Стили для подсветки синтаксиса
import 'katex/dist/katex.min.css'; // Стили для KaTeX (LaTeX формулы)

const MarkdownRenderer = ({ content, className = '' }) => {
  const [copiedCodeBlocks, setCopiedCodeBlocks] = useState(new Set());

  // Функция для копирования кода
  const copyCodeToClipboard = async (code, blockIndex) => {
    try {
      if (navigator.clipboard && window.ClipboardItem) {
        await navigator.clipboard.writeText(code);
      } else {
        // Fallback для старых браузеров
        const textArea = document.createElement('textarea');
        textArea.value = code;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      
      // Добавляем индекс в множество скопированных
      setCopiedCodeBlocks(prev => new Set([...prev, blockIndex]));
      
      // Убираем индикатор через 2 секунды
      setTimeout(() => {
        setCopiedCodeBlocks(prev => {
          const newSet = new Set(prev);
          newSet.delete(blockIndex);
          return newSet;
        });
      }, 2000);
      
    } catch (error) {
      console.error('Ошибка копирования кода:', error);
    }
  };

  // Предварительная обработка для definition lists и HTML тегов
  const processDefinitionLists = (text) => {
    // Обрабатываем definition lists в формате "Термин:: Описание"
    const lines = text.split('\n');
    const processedLines = [];
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const definitionMatch = line.match(/^(.+?)::\s*(.+)$/);
      
      if (definitionMatch) {
        const [, term, description] = definitionMatch;
        
        // Если это первая строка definition list, добавляем открывающий тег
        if (i === 0 || !lines[i - 1].match(/^(.+?)::\s*(.+)$/)) {
          processedLines.push('<dl class="markdown-definition-list">');
        }
        
        processedLines.push(`<dt class="markdown-definition-term">${term}</dt>`);
        processedLines.push(`<dd class="markdown-definition-description">${description}</dd>`);
        
        // Если следующая строка не definition list, закрываем тег
        if (i === lines.length - 1 || !lines[i + 1].match(/^(.+?)::\s*(.+)$/)) {
          processedLines.push('</dl>');
        }
      } else {
        processedLines.push(line);
      }
    }
    
    return processedLines.join('\n');
  };

  // Обработка HTML тегов для предотвращения обрезания
  const processHtmlTags = (text) => {
    // Сначала защищаем код-блоки от обработки
    const codeBlocks = [];
    let processedText = text.replace(/```[\s\S]*?```/g, (match) => {
      const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
      codeBlocks.push(match);
      return placeholder;
    });
    
    // Также защищаем inline код
    processedText = processedText.replace(/`[^`]+`/g, (match) => {
      const placeholder = `__INLINE_CODE_${codeBlocks.length}__`;
      codeBlocks.push(match);
      return placeholder;
    });
    
    // Теперь обрабатываем HTML теги только вне код-блоков
    processedText = processedText.replace(/<([^>]+)>/g, (match, content) => {
      // Заменяем пробелы внутри тегов на неразрывные пробелы
      const processedContent = content.replace(/\s+/g, '&nbsp;');
      return `<${processedContent}>`;
    });
    
    // Восстанавливаем код-блоки
    codeBlocks.forEach((codeBlock, index) => {
      processedText = processedText.replace(`__CODE_BLOCK_${index}__`, codeBlock);
      processedText = processedText.replace(`__INLINE_CODE_${index}__`, codeBlock);
    });
    
    return processedText;
  };

  // Мемоизируем обработку контента для предотвращения лишних вычислений
  const processedContent = useMemo(() => {
    return processHtmlTags(processDefinitionLists(content));
  }, [content]);

  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown
        remarkPlugins={[
          remarkGfm,
          remarkMath
        ]}
        rehypePlugins={[rehypeRaw, rehypeHighlight, rehypeKatex]}
        components={{
          // Кастомные компоненты для лучшего отображения
          code({ node, inline, className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            
            // Правильно извлекаем текстовое содержимое из React элементов
            const extractTextFromChildren = (children) => {
              if (typeof children === 'string') {
                return children;
              }
              if (Array.isArray(children)) {
                return children.map(child => extractTextFromChildren(child)).join('');
              }
              if (children && typeof children === 'object' && children.props) {
                return extractTextFromChildren(children.props.children);
              }
              return String(children || '');
            };
            
            const codeText = extractTextFromChildren(children).replace(/\n$/, '');
            // Создаем стабильный ID на основе содержимого кода (безопасно для Unicode)
            const createHash = (str) => {
              let hash = 0;
              for (let i = 0; i < str.length; i++) {
                const char = str.charCodeAt(i);
                hash = ((hash << 5) - hash) + char;
                hash = hash & hash; // Convert to 32bit integer
              }
              return Math.abs(hash).toString(36);
            };
            const blockIndex = createHash(codeText.substring(0, 100));
            
            return !inline && match ? (
              <div className="code-block-container">
                <div className="code-block-header">
                  <span className="code-language">{match[1]}</span>
                  <button
                    className={`copy-code-btn ${copiedCodeBlocks.has(blockIndex) ? 'copied' : ''}`}
                    onClick={() => copyCodeToClipboard(codeText, blockIndex)}
                    title="Копировать код"
                  >
                    {copiedCodeBlocks.has(blockIndex) ? 'Скопировано' : 'Копировать'}
                  </button>
                </div>
                <pre className="code-block">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              </div>
            ) : (
              <code className="inline-code" {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="table-wrapper">
                <table className="markdown-table">
                  {children}
                </table>
              </div>
            );
          },
          blockquote({ children }) {
            return (
              <blockquote className="markdown-blockquote">
                {children}
              </blockquote>
            );
          },
          h1({ children }) {
            return <h1 className="markdown-h1">{children}</h1>;
          },
          h2({ children }) {
            return <h2 className="markdown-h2">{children}</h2>;
          },
          h3({ children }) {
            return <h3 className="markdown-h3">{children}</h3>;
          },
          h4({ children }) {
            return <h4 className="markdown-h4">{children}</h4>;
          },
          h5({ children }) {
            return <h5 className="markdown-h5">{children}</h5>;
          },
          h6({ children }) {
            return <h6 className="markdown-h6">{children}</h6>;
          },
          p({ children }) {
            return <p className="markdown-paragraph">{children}</p>;
          },
          ul({ children }) {
            return <ul className="markdown-list">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="markdown-ordered-list">{children}</ol>;
          },
          li({ children }) {
            return <li className="markdown-list-item">{children}</li>;
          },
          a({ href, children }) {
            return (
              <a 
                href={href} 
                target="_blank" 
                rel="noopener noreferrer"
                className="markdown-link"
              >
                {children}
              </a>
            );
          },
          strong({ children }) {
            return <strong className="markdown-strong">{children}</strong>;
          },
          em({ children }) {
            return <em className="markdown-em">{children}</em>;
          },
          del({ children }) {
            return <del className="markdown-del">{children}</del>;
          },
          hr() {
            return <hr className="markdown-hr" />;
          },
          br() {
            return <br className="markdown-br" />;
          },
          // Поддержка новых HTML элементов
          u({ children }) {
            return <u className="markdown-underline">{children}</u>;
          },
          sub({ children }) {
            return <sub className="markdown-sub">{children}</sub>;
          },
          sup({ children }) {
            return <sup className="markdown-sup">{children}</sup>;
          },
          details({ children }) {
            return <details className="markdown-details">{children}</details>;
          },
          summary({ children }) {
            return <summary className="markdown-summary">{children}</summary>;
          },
          audio({ src, controls, ...props }) {
            return <audio src={src} controls={controls} className="markdown-audio" {...props} />;
          },
          video({ src, controls, ...props }) {
            return <video src={src} controls={controls} className="markdown-video" {...props} />;
          },
          // Поддержка task lists (уже включено в remark-gfm)
          input({ type, checked, ...props }) {
            if (type === 'checkbox') {
              return <input type="checkbox" checked={checked} className="markdown-checkbox" readOnly {...props} />;
            }
            return <input type={type} {...props} />;
          },
          // Поддержка definition lists
          dl({ children }) {
            return <dl className="markdown-definition-list">{children}</dl>;
          },
          dt({ children }) {
            return <dt className="markdown-definition-term">{children}</dt>;
          },
          dd({ children }) {
            return <dd className="markdown-definition-description">{children}</dd>;
          }
        }}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
};

export default memo(MarkdownRenderer);
