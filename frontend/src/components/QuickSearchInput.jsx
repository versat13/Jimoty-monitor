import { useState, useEffect, useRef, useCallback } from "react";
import { Search, X, Clock } from "lucide-react";
import { api } from "../api/client";

/**
 * 既存タブ (フィルタ/NG/すべて/終了/監視) 共通の、一時的な検索
 * フィルタ (2026-09-08新設)。
 *
 * 「検索」タブ (PickupSearchBuilder) との違い:
 * - こちらは検索条件自体を保存しない。タブを離れる・ページを閉じる
 *   などで都度リセットされる。
 * - ただし打ち込んだワードの履歴だけはサーバー側DBに保存され、
 *   次回以降も入力候補として使える (ユーザーとの打ち合わせで合意)。
 * - 単純な部分一致 (大小文字を区別しない) で判定する。正規表現の
 *   ビルダーのような複雑な条件は「検索」タブの役割。
 */
export default function QuickSearchInput({ value, onChange }) {
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState([]);
  const containerRef = useRef(null);

  const loadHistory = useCallback(() => {
    api
      .getSearchHistory()
      .then((r) => setHistory(r.queries || []))
      .catch(() => setHistory([]));
  }, []);

  useEffect(() => {
    function onClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setShowHistory(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const commitToHistory = (query) => {
    const trimmed = query.trim();
    if (!trimmed) return;
    // 失敗しても検索自体は継続できるべきなので、履歴保存の失敗は
    // 静かに無視する (ユーザー体験を止めない)。
    api.addSearchHistory(trimmed).catch(() => {});
  };

  const handleBlur = () => {
    commitToHistory(value);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      commitToHistory(value);
      setShowHistory(false);
    }
  };

  const handleFocus = () => {
    loadHistory();
    setShowHistory(true);
  };

  const pickHistoryItem = (query) => {
    onChange(query);
    setShowHistory(false);
  };

  return (
    <div ref={containerRef} className="relative flex-1 min-w-[140px]">
      <div className="flex items-center gap-1.5 bg-white border border-line rounded-lg px-2 py-1.5">
        <Search size={13} className="text-ink/30 shrink-0" />
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          placeholder="キーワードで絞り込み"
          className="flex-1 min-w-0 text-xs focus:outline-none bg-transparent"
        />
        {value && (
          <button
            onClick={() => onChange("")}
            className="text-ink/30 hover:text-alert shrink-0"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {showHistory && history.length > 0 && (
        <div className="absolute z-20 mt-1 w-full bg-white border border-line rounded-lg shadow-card py-1 max-h-48 overflow-y-auto">
          {history.map((q) => (
            <button
              key={q}
              onMouseDown={(e) => {
                // input の blur より先にクリックを処理したいので
                // mousedown で拾う (blur で閉じてしまう前に選択させる)。
                e.preventDefault();
                pickHistoryItem(q);
              }}
              className="w-full flex items-center gap-1.5 text-left text-xs text-ink/70 px-2.5 py-1.5 hover:bg-paper/60"
            >
              <Clock size={11} className="text-ink/30 shrink-0" />
              <span className="truncate">{q}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
