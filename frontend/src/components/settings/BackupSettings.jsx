import { useState, useRef } from "react";
import { Download, Upload, AlertTriangle } from "lucide-react";
import { api } from "../../api/client";

export default function BackupSettings() {
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState(null);
  const [importedAt, setImportedAt] = useState(null);
  const fileInputRef = useRef(null);

  const handleExport = async () => {
    setError(null);
    setExporting(true);
    try {
      const data = await api.exportSettings();
      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      // ファイル名に日付を入れておく (複数回エクスポートしても
      // 上書きされず、いつの時点の設定か分かるように)。
      const today = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      const dateStr = `${today.getFullYear()}${pad(today.getMonth() + 1)}${pad(today.getDate())}`;
      a.href = url;
      a.download = `jimoty-monitor-settings_${dateStr}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setExporting(false);
    }
  };

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // 同じファイルを連続選択してもonChangeが発火するようにリセット
    if (!file) return;

    // 2026-09-08: インポートは既存の全設定を完全に置き換える破壊的な
    // 操作のため、実行前に確認ダイアログを挟む。「今すぐ更新」等の
    // 通常操作とは異なり取り消せないため、ここだけは慎重にしている。
    if (!window.confirm("現在のNGワード・NGカテゴリ・ユーザー設定・検索条件などがすべて上書きされます。よろしいですか？")) {
      return;
    }

    setError(null);
    setImporting(true);
    try {
      const text = await file.text();
      let data;
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error("選択したファイルはJSON形式として読み込めませんでした");
      }
      await api.importSettings(data);
      setImportedAt(Date.now());
    } catch (e) {
      setError(e.message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div>
      <p className="text-xs text-ink/50 mb-4">
        NGワード・NGカテゴリ・ユーザー設定・取得範囲・自動更新間隔・検索タブの条件を、まとめてファイルに書き出したり読み込んだりできます。
      </p>

      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      <div className="bg-white border border-line rounded-xl p-3 mb-3">
        <p className="text-sm font-bold mb-1">設定をエクスポート</p>
        <p className="text-xs text-ink/50 mb-3">
          現在の設定をJSONファイルとしてダウンロードします。
        </p>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="w-full flex items-center justify-center gap-1.5 bg-indigo text-white rounded-xl py-2.5 text-sm font-bold disabled:opacity-50"
        >
          <Download size={15} />
          {exporting ? "書き出し中…" : "エクスポート"}
        </button>
      </div>

      <div className="bg-white border border-line rounded-xl p-3">
        <p className="text-sm font-bold mb-1">設定をインポート</p>
        <p className="text-xs text-ink/50 mb-2">
          エクスポートしたJSONファイルを読み込み、現在の設定を置き換えます。
        </p>
        <div className="flex items-start gap-1.5 text-[11px] text-alert bg-alert/5 border border-alert/20 rounded-lg px-2.5 py-2 mb-3">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          <span>現在のNGワード・NGカテゴリ・ユーザー設定・検索条件などは、読み込んだ内容ですべて上書きされます。元に戻すことはできません。</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json"
          onChange={handleFileSelected}
          className="hidden"
        />
        <button
          onClick={handleImportClick}
          disabled={importing}
          className="w-full flex items-center justify-center gap-1.5 bg-white text-ink border border-line rounded-xl py-2.5 text-sm font-bold disabled:opacity-50 hover:bg-paper/60"
        >
          <Upload size={15} />
          {importing ? "読み込み中…" : "ファイルを選択してインポート"}
        </button>
        {importedAt && (
          <p className="text-center text-[11px] text-ink/40 mt-2">インポートしました</p>
        )}
      </div>
    </div>
  );
}
