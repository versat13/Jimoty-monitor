import { useState, useEffect, useCallback } from "react";
import { api } from "../../api/client";
import RetentionSettings from "./RetentionSettings";

export default function ScanRangeSettings() {
  const [mode, setMode] = useState("pages");
  const [value, setValue] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getScanRangeSettings()
      .then((s) => {
        setMode(s.scan_range_mode);
        setValue(s.scan_range_value);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const payload = {
        scan_range_mode: mode,
        scan_range_value: Number(value),
      };
      await api.updateScanRangeSettings(payload);
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
        「今すぐ更新」を実行したとき、一覧を何ページ・何日分まで遡って確認するかを設定します。
        ページ数指定・日数指定はどちらか一方を選びます。
        既にDBに登録済みの投稿は、価格・タイトルの差分確認のみを行い、個別ページへは再アクセスしません
        （アクセス数を抑えるため）。
      </p>

      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      <div className="bg-white border border-line rounded-xl p-3 mb-4">
        <div className="flex gap-1 bg-line/50 rounded-full p-1 mb-3">
          <button
            onClick={() => setMode("pages")}
            className={`flex-1 text-xs font-bold py-1.5 rounded-full transition-colors ${
              mode === "pages" ? "bg-white text-indigo shadow-sm" : "text-ink/40"
            }`}
          >
            ページ数で指定
          </button>
          <button
            onClick={() => setMode("days")}
            className={`flex-1 text-xs font-bold py-1.5 rounded-full transition-colors ${
              mode === "days" ? "bg-white text-indigo shadow-sm" : "text-ink/40"
            }`}
          >
            過去n日で指定
          </button>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink/60 shrink-0">
            {mode === "pages" ? "最大ページ数" : "遡る日数"}
          </span>
          <input
            type="number"
            min={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="flex-1 bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
          />
          <span className="text-ink/40 shrink-0">{mode === "pages" ? "ページ" : "日"}</span>
        </label>

        {mode === "pages" ? (
          <p className="text-[11px] text-ink/40 mt-2">
            1ページ目から指定ページ目まで固定的に巡回します（デフォルト: 1ページ）。
          </p>
        ) : (
          <p className="text-[11px] text-ink/40 mt-2">
            一覧を新着順に辿り、投稿の更新日（無ければ作成日）が指定日数より古くなった時点で巡回を打ち切ります。
          </p>
        )}
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

      <RetentionSettings />
    </div>
  );
}
