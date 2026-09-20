import { useState, useEffect, useCallback } from "react";
import { api } from "../../api/client";

export default function RetentionSettings() {
  const [enabled, setEnabled] = useState(true);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getRetentionSettings()
      .then((s) => {
        setEnabled(s.enabled);
        setDays(s.retention_days);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      await api.updateRetentionSettings({ enabled, retention_days: Number(days) });
      setSavedAt(Date.now());
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-center text-ink/30 text-sm py-8 mt-6">読み込み中…</p>;
  }

  return (
    <div className="mt-6 pt-6 border-t border-line">
      <h2 className="font-bold text-sm mb-1">保存期間</h2>
      <p className="text-xs text-ink/50 mb-4">
        一覧を溜め込みすぎないよう、最後に確認できてから一定期間が経過した投稿を自動的に削除します。
        受付中（公開中）の投稿も対象です。巡回のたびに一覧で存在を確認できていれば削除されません。
        監視中（☆登録・監視ユーザー）の投稿は、監視を解除するまで削除されません。
      </p>

      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      <div className="bg-white border border-line rounded-xl p-3 mb-4">
        <label className="flex items-center justify-between text-sm mb-3">
          <span className="text-ink/70 font-medium">保存期間による自動削除</span>
          <button
            onClick={() => setEnabled((v) => !v)}
            role="switch"
            aria-checked={enabled}
            className={`relative w-10 h-6 rounded-full transition-colors ${
              enabled ? "bg-indigo" : "bg-line"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </label>

        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink/60 shrink-0">最後に確認できてから</span>
          <input
            type="number"
            min={1}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            disabled={!enabled}
            className="flex-1 bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30 disabled:opacity-40"
          />
          <span className="text-ink/40 shrink-0">日</span>
        </label>
        <p className="text-[11px] text-ink/40 mt-2">
          「終了」タブの投稿は、一覧から消えてからの経過日数で判定します。
        </p>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="w-full bg-indigo text-white rounded-xl py-2.5 text-sm font-bold disabled:opacity-50"
      >
        {saving ? "保存中…" : "保存する"}
      </button>
      {savedAt && (
        <p className="text-center text-[11px] text-ink/40 mt-2">保存しました</p>
      )}
    </div>
  );
}
