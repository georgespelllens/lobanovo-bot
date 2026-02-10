import { useState, useRef, useEffect } from "react";
import { Send, Clock, ChevronDown, ChevronUp } from "lucide-react";
import { sendAudit, getAuditHistory } from "@/api/endpoints";
import { haptic } from "@/lib/telegram";

interface AuditHistoryItem {
  id: number;
  preview: string;
  review: string;
  created_at: string;
}

export default function Audit() {
  const [text, setText] = useState("");
  const [result, setResult] = useState("");
  const [isAuditing, setIsAuditing] = useState(false);
  const [history, setHistory] = useState<AuditHistoryItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getAuditHistory()
      .then((res: any) => {
        if (res.ok && res.data) {
          setHistory(res.data.audits);
        }
      })
      .catch(console.error);
  }, []);

  async function handleAudit() {
    if (!text.trim() || text.trim().length < 50 || isAuditing) return;

    haptic("medium");
    setIsAuditing(true);
    setResult("");

    try {
      const stream = sendAudit(text);
      for await (const event of stream) {
        if (event.type === "token" && event.content) {
          setResult((prev) => prev + event.content);
        } else if (event.type === "done") {
          haptic("success");
        } else if (event.type === "error") {
          setResult(event.content || "Ошибка при анализе");
        }
      }
    } catch {
      setResult("Произошла ошибка. Попробуй ещё раз.");
    }

    setIsAuditing(false);
  }

  useEffect(() => {
    if (result) {
      resultRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [result]);

  const charCount = text.length;
  const isValid = charCount >= 50;

  return (
    <div className="px-4 py-5 space-y-4">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold">Аудит поста</h2>
        <p className="text-sm text-tg-hint mt-1">
          Вставь текст поста — разберу по 6 критериям Лобанова
        </p>
      </div>

      {/* Input */}
      <div className="relative">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Вставь текст поста сюда..."
          rows={8}
          className="w-full bg-tg-surface text-tg-text placeholder-tg-hint rounded-xl px-4 py-3 text-sm resize-none outline-none focus:ring-1 focus:ring-accent/50"
        />
        <div className="absolute bottom-3 right-3 flex items-center gap-2">
          <span className={`text-xs ${isValid ? "text-tg-hint" : "text-red-400"}`}>
            {charCount}
          </span>
        </div>
      </div>

      {/* Submit */}
      <button
        onClick={handleAudit}
        disabled={!isValid || isAuditing}
        className="w-full bg-accent text-white font-medium rounded-xl py-3 flex items-center justify-center gap-2 disabled:opacity-40 active:scale-[0.98] transition-all"
      >
        {isAuditing ? (
          <>
            <div className="flex gap-1">
              <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white" />
              <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white" />
              <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white" />
            </div>
            Анализирую...
          </>
        ) : (
          <>
            <Send size={16} />
            Разобрать
          </>
        )}
      </button>

      {!isValid && charCount > 0 && (
        <p className="text-xs text-red-400 -mt-2">Минимум 50 символов ({50 - charCount} ещё)</p>
      )}

      {/* Result */}
      {result && (
        <div ref={resultRef} className="bg-tg-surface rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">Результат</h3>
          <p className="text-sm text-tg-text leading-relaxed whitespace-pre-wrap">{result}</p>
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="flex items-center gap-2 text-sm text-tg-hint"
          >
            <Clock size={14} />
            История аудитов ({history.length})
            {showHistory ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>

          {showHistory && (
            <div className="space-y-2 mt-3">
              {history.map((item) => (
                <div key={item.id} className="bg-tg-surface rounded-xl p-3">
                  <p className="text-xs text-tg-hint mb-1">
                    {new Date(item.created_at).toLocaleDateString("ru-RU")}
                  </p>
                  <p className="text-sm text-tg-text line-clamp-2">{item.preview}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
