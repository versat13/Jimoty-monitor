import { useState, useEffect, useCallback } from "react";
import { Ban, Eye, Plus, X } from "lucide-react";
import { api } from "../../api/client";

export default function SellerRuleSettings() {
  const [items, setItems] = useState([]);
  const [sellerId, setSellerId] = useState("");
  const [sellerName, setSellerName] = useState("");
  const [ruleType, setRuleType] = useState("ng");
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.listSellerRules("all").then(setItems).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const add = async () => {
    if (!sellerId.trim()) return;
    try {
      await api.createSellerRule({
        seller_id: sellerId.trim(),
        seller_name: sellerName.trim() || null,
        rule_type: ruleType,
      });
      setSellerId("");
      setSellerName("");
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div>
      <p className="text-xs text-ink/50 mb-3">
        NGユーザーの投稿もデータ自体は取得し続けます（表示のみ除外されます）。監視ユーザーは今後の一覧で目印表示に使う想定です。
      </p>

      <div className="flex flex-col gap-2 mb-4">
        <input
          value={sellerId}
          onChange={(e) => setSellerId(e.target.value)}
          placeholder="出品者ID（プロフィールURLの末尾）"
          className="bg-white border border-line rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
        />
        <input
          value={sellerName}
          onChange={(e) => setSellerName(e.target.value)}
          placeholder="表示名（任意）"
          className="bg-white border border-line rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
        />
        <div className="flex gap-2">
          <div className="flex-1 flex bg-line/50 rounded-xl p-1">
            <button
              onClick={() => setRuleType("ng")}
              className={`flex-1 flex items-center justify-center gap-1 text-xs font-bold py-1.5 rounded-lg ${
                ruleType === "ng" ? "bg-white text-alert shadow-sm" : "text-ink/40"
              }`}
            >
              <Ban size={12} /> NG
            </button>
            <button
              onClick={() => setRuleType("watch")}
              className={`flex-1 flex items-center justify-center gap-1 text-xs font-bold py-1.5 rounded-lg ${
                ruleType === "watch" ? "bg-white text-indigo shadow-sm" : "text-ink/40"
              }`}
            >
              <Eye size={12} /> 監視
            </button>
          </div>
          <button
            onClick={add}
            className="bg-indigo text-white rounded-xl px-3 flex items-center justify-center"
          >
            <Plus size={18} />
          </button>
        </div>
      </div>

      {error && <p className="text-alert text-xs mb-2">{error}</p>}

      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between bg-white border border-line rounded-xl px-3 py-2"
          >
            <div className="flex items-center gap-2">
              {item.rule_type === "ng" ? (
                <Ban size={14} className="text-alert shrink-0" />
              ) : (
                <Eye size={14} className="text-indigo shrink-0" />
              )}
              <span className="text-sm font-medium">
                {item.seller_name || item.seller_id}
              </span>
            </div>
            <button
              onClick={() => api.deleteSellerRule(item.id).then(load)}
              className="text-ink/30 hover:text-alert"
            >
              <X size={16} />
            </button>
          </div>
        ))}
        {items.length === 0 && (
          <p className="text-center text-ink/30 text-sm py-8">登録済みユーザーはいません</p>
        )}
      </div>
    </div>
  );
}
