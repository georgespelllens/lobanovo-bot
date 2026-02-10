import { ThumbsUp, ThumbsDown } from "lucide-react";
import { haptic } from "@/lib/telegram";

interface Props {
  messageId: number;
  currentRating?: number | null;
  onRate: (messageId: number, rating: 1 | -1) => void;
}

export default function FeedbackButtons({ messageId, currentRating, onRate }: Props) {
  return (
    <div className="flex gap-2 mt-1">
      <button
        onClick={() => {
          haptic("light");
          onRate(messageId, 1);
        }}
        className={`p-1.5 rounded-lg transition-colors ${
          currentRating === 1
            ? "bg-green-500/20 text-green-400"
            : "text-tg-hint hover:text-tg-text hover:bg-tg-surface"
        }`}
      >
        <ThumbsUp size={14} />
      </button>
      <button
        onClick={() => {
          haptic("light");
          onRate(messageId, -1);
        }}
        className={`p-1.5 rounded-lg transition-colors ${
          currentRating === -1
            ? "bg-red-500/20 text-red-400"
            : "text-tg-hint hover:text-tg-text hover:bg-tg-surface"
        }`}
      >
        <ThumbsDown size={14} />
      </button>
    </div>
  );
}
