import { useEffect, useRef } from 'react';

export default function ChatInterface({
  messages,
  prompts,
  onPromptClick,
  onSubmit,
  disabled = false,
  title = 'Touchline Coach',
  subtitle,
}) {
  const inputRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    if (endRef.current) {
      endRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const handleSubmit = (event) => {
    event.preventDefault();
    const value = inputRef.current?.value.trim();
    if (!value || disabled) return;
    onSubmit(value);
    if (inputRef.current) {
      inputRef.current.value = '';
    }
  };

  return (
    <div className="chat-shell">
      <div className="chat-header">
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>

      <div className="chat-history">
        {messages.map((message, index) => (
          <div key={index} className={`chat-bubble chat-bubble--${message.role}`}>
            {message.content}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="chat-suggestions">
        <span>Set Plays</span>
        <div className="chat-prompt-list">
          {prompts.map((prompt) => (
            <button
              key={prompt.id}
              type="button"
              className="chat-prompt"
              onClick={() => onPromptClick(prompt)}
              disabled={disabled}
            >
              {prompt.label}
            </button>
          ))}
        </div>
      </div>

      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          ref={inputRef}
          placeholder="Ask your touchline assistant…"
          aria-label="Chat input"
          disabled={disabled}
        />
        <button type="submit" disabled={disabled}>Send</button>
      </form>
    </div>
  );
}
