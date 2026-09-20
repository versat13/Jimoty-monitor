import { useState, useEffect, useCallback } from "react";
import { Plus, X } from "lucide-react";
import { api } from "../../api/client";

export default function KeywordSettings() {
  const [items, setItems] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.listNgKeywords().then(setItems).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const add = async () => {
    if (!input.trim()) return;
    try {
      await api.createNgKeyword(input.trim());
      setInput("");
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div>
      <p className="text-xs text-ink/50 mb-3">
        タイトル・説明文にこの語を含む投稿は「表示中」タブから除外されます（データ自体は取得し続けます）。
      </p>

      <div className="flex gap-2 mb-4">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="NGワードを入力"
          className="flex-1 bg-white border border-line rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
        />
        <button
          onClick={add}
          className="bg-indigo text-white rounded-xl px-3 flex items-center justify-center"
        >
          <Plus size={18} />
        </button>
      </div>

      {error && <p className="text-alert text-xs mb-2">{error}</p>}

      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between bg-white border border-line rounded-xl px-3 py-2"
          >
            <button
              onClick={() => api.toggleNgKeyword(item.id).then(load)}
              className={`text-sm font-medium ${item.is_active ? "" : "text-ink/30 line-through"}`}
            >
              {item.keyword}
            </button>
            <button
              onClick={() => api.deleteNgKeyword(item.id).then(load)}
              className="text-ink/30 hover:text-alert"
            >
              <X size={16} />
            </button>
          </div>
        ))}
        {items.length === 0 && (
          <p className="text-center text-ink/30 text-sm py-8">NGワードは未登録です</p>
        )}
      </div>
    </div>
  );
}
