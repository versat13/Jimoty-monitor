import { useState } from "react";
import { Star } from "lucide-react";
import { api } from "../api/client";

export default function WatchButton({ articleId, isWatched, onChange, size = 16 }) {
  const [pending, setPending] = useState(false);

  const toggle = async (e) => {
    e.stopPropagation();
    if (pending) return;
    setPending(true);
    const next = !isWatched;
    onChange?.(next); // 楽観的更新: レスポンスを待たず即座に見た目を変える
    try {
      if (next) {
        await api.watchArticle(articleId);
      } else {
        await api.unwatchArticle(articleId);
      }
    } catch {
      onChange?.(!next); // 失敗時は元に戻す
    } finally {
      setPending(false);
    }
  };

  return (
    <button
      onClick={toggle}
      title={isWatched ? "監視を解除" : "監視リストに追加"}
      className={`transition-colors ${
        isWatched ? "text-clay" : "text-ink/25 hover:text-clay"
      }`}
    >
      <Star size={size} className={isWatched ? "fill-clay" : ""} />
    </button>
  );
}
