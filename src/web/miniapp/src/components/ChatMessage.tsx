import type { ChatMsg } from "@/store/chat";
import FeedbackButtons from "./FeedbackButtons";

interface Props {
  msg: ChatMsg;
  onRate: (messageId: number, rating: 1 | -1) => void;
}

export default function ChatMessage({ msg, onRate }: Props) {
  const isUser = msg.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 ${
          isUser
            ? "bg-accent text-white rounded-br-md"
            : "bg-tg-surface text-tg-text rounded-bl-md"
        }`}
      >
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>

        {msg.isStreaming && (
          <div className="flex gap-1 mt-1">
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-tg-hint" />
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-tg-hint" />
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-tg-hint" />
          </div>
        )}

        {!isUser && !msg.isStreaming && msg.id && (
          <FeedbackButtons
            messageId={msg.id}
            currentRating={msg.rating}
            onRate={onRate}
          />
        )}
      </div>
    </div>
  );
}
