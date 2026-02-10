import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { useChatStore, type ChatMsg } from "@/store/chat";
import { sendChatMessage, getChatHistory, sendChatFeedback } from "@/api/endpoints";
import ChatMessage from "@/components/ChatMessage";
import { haptic } from "@/lib/telegram";

export default function Chat() {
  const {
    messages,
    isLoading,
    hasMore,
    setMessages,
    addMessage,
    appendToLast,
    finishStreaming,
    updateRating,
    setLoading,
    setHasMore,
    prependMessages,
  } = useChatStore();

  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const [historyLoaded, setHistoryLoaded] = useState(false);

  // Load history on mount
  useEffect(() => {
    if (historyLoaded) return;
    setHistoryLoaded(true);

    getChatHistory(0, 30)
      .then((res: any) => {
        if (res.ok && res.data) {
          setMessages(res.data.messages);
          setHasMore(res.data.has_more);
        }
      })
      .catch(console.error);
  }, []);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    const text = input.trim();
    if (!text || isSending) return;

    haptic("light");
    setInput("");
    setIsSending(true);

    // Add user message
    addMessage({ role: "user", content: text });

    // Add placeholder assistant message
    addMessage({ role: "assistant", content: "", isStreaming: true });

    try {
      const stream = sendChatMessage(text);
      for await (const event of stream) {
        if (event.type === "token" && event.content) {
          appendToLast(event.content);
        } else if (event.type === "done" && event.message_id) {
          finishStreaming(event.message_id);
          haptic("success");
        } else if (event.type === "error") {
          appendToLast(event.content || "Ошибка");
          finishStreaming(0);
        }
      }
    } catch (err) {
      appendToLast("Произошла ошибка. Попробуй ещё раз.");
      finishStreaming(0);
    }

    setIsSending(false);
  }

  function handleRate(messageId: number, rating: 1 | -1) {
    updateRating(messageId, rating);
    sendChatFeedback(messageId, rating).catch(console.error);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-112px)]">
      {/* Messages */}
      <div ref={chatContainerRef} className="flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 && !isLoading && (
          <div className="flex flex-col items-center justify-center h-full text-center px-6">
            <div className="text-4xl mb-4">🐺</div>
            <h2 className="text-base font-semibold mb-2">Приёмная Лобанова</h2>
            <p className="text-sm text-tg-hint leading-relaxed">
              Задай вопрос о личном бренде, карьере, контенте или публичных
              выступлениях. Отвечаю на основе 3000+ постов Кости.
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <ChatMessage key={msg.id || `temp-${i}`} msg={msg} onRate={handleRate} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="chat-input-fixed bg-tg-bg/95 backdrop-blur-md border-t border-white/5 px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Задай вопрос..."
            rows={1}
            className="flex-1 bg-tg-surface text-tg-text placeholder-tg-hint rounded-xl px-4 py-2.5 text-sm resize-none outline-none focus:ring-1 focus:ring-accent/50 max-h-32"
            style={{ minHeight: "40px" }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isSending}
            className="w-10 h-10 rounded-full bg-accent flex items-center justify-center shrink-0 disabled:opacity-40 active:scale-90 transition-all"
          >
            <Send size={18} className="text-white" />
          </button>
        </div>
      </div>
    </div>
  );
}
