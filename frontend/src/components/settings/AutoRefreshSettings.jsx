import { useState, useEffect, useCallback } from "react";
import { api } from "../../api/client";

export default function AutoRefreshSettings() {
  const [autoInterval, setAutoInterval] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getScanRangeSettings()
      .then((s) => {
        setAutoInterval(
          s.auto_scan_interval_minutes != null ? String(s.auto_scan_interval_minutes) : ""
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      await api.updateAutoScanInterval(autoInterval === "" ? null : Number(autoInterval));
      setSavedAt(Date.now());
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-center text-ink/30 text-sm py-8">読み込み中…</p>;
  }

  return (
    <div>
      <p className="text-xs text-ink/50 mb-4">
        指定した間隔で自動的に一覧を巡回します。このソフトを起動しているサーバーが動作している間、設定した分数ごとに「今すぐ更新」と同じ処理が自動実行されます。
      </p>

      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      {/*
        2026-09-09: 自動更新機能を実装済み (scheduler/auto_refresh.py。
        サーバー側 (uvicornプロセス) の定期実行ループが、ここで保存した
        間隔ごとに巡回する)。以前の「準備中」の無効化見た目・注記は
        不要になったため外し、実装済みであることが伝わる説明文に
        変更した。
      */}
      <div className="bg-white border border-line rounded-xl p-3 mb-4">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink/60 shrink-0">自動更新の間隔</span>
          <input
            type="number"
            min={1}
            placeholder="未設定"
            value={autoInterval}
            onChange={(e) => setAutoInterval(e.target.value)}
            className="flex-1 bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
          />
          <span className="text-ink/40 shrink-0">分</span>
        </label>
        <p className="text-[11px] text-ink/40 mt-2">
          未設定（空欄）の場合、自動更新は行われません。このソフトを起動しているサーバー側で、指定した間隔ごとに自動的に巡回します。ブラウザを閉じていても動作します。初期設定では30分間隔になっています。
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

