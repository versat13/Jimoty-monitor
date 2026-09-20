import { useState } from "react";
import { AlertTriangle, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../../api/client";

/**
 * 「設定を初期化」「取得済みデータを全削除」のリセット画面
 * (2026-09-14新設)。
 *
 * どちらも取り消しのできない破壊的操作のため、実行前に必ず
 * confirm() ダイアログを挟む。「全リセット」という単独のボタンは
 * あえて用意せず、この2つを両方実行すれば結果的に全リセット相当に
 * なる、という設計方針 (ユーザーとの合意事項)。
 */
export default function ResetSettings() {
  const [resettingSettings, setResettingSettings] = useState(false);
  const [deletingData, setDeletingData] = useState(false);
  const [message, setMessage] = useState(null);

  const handleResetSettings = async () => {
    if (
      !confirm(
        "NGワード・NGカテゴリ・ユーザー・地域・取得範囲・自動更新・通知設定などが全て初期値に戻ります。\n取得済みの投稿データには影響しません。\n\nこの操作は取り消せません。実行しますか？"
      )
    ) {
      return;
    }
    setResettingSettings(true);
    setMessage(null);
    try {
      await api.resetSettings();
      setMessage({ ok: true, text: "設定を初期化しました。" });
    } catch (e) {
      setMessage({ ok: false, text: e.message });
    } finally {
      setResettingSettings(false);
    }
  };

  const handleDeleteAllScrapedData = async () => {
    if (
      !confirm(
        "取得済みの投稿データ（投稿本体・出品者情報・価格履歴・削除履歴・☆監視）が全て削除されます。\n設定（NGワード等）には影響しません。\n\nこの操作は取り消せません。実行しますか？"
      )
    ) {
      return;
    }
    setDeletingData(true);
    setMessage(null);
    try {
      await api.deleteAllScrapedData();
      setMessage({ ok: true, text: "取得済みデータを全削除しました。" });
    } catch (e) {
      setMessage({ ok: false, text: e.message });
    } finally {
      setDeletingData(false);
    }
  };

  return (
    <div>
      <p className="text-xs text-ink/50 mb-4">
        以下はいずれも取り消しのできない操作です。実行前に必ず内容をご確認ください。両方を実行すると、アプリを初めて使う状態に戻ります。
      </p>

      {message && (
        <p
          className={`text-xs rounded-lg px-3 py-2 mb-3 ${
            message.ok
              ? "text-ink/60 bg-line/30"
              : "text-alert bg-alert/5 border border-alert/20"
          }`}
        >
          {message.text}
        </p>
      )}

      <div className="bg-white border border-line rounded-xl p-3 mb-3">
        <div className="flex items-center gap-2 mb-1.5">
          <RotateCcw size={14} className="text-ink/50" />
          <p className="text-sm font-bold">設定を初期化</p>
        </div>
        <p className="text-[11px] text-ink/40 mb-3">
          NGワード・NGカテゴリ・ユーザー・地域・取得範囲・自動更新・通知設定などが初期値に戻ります。取得済みの投稿データは残ります。
        </p>
        <button
          onClick={handleResetSettings}
          disabled={resettingSettings}
          className="w-full border border-alert/30 text-alert rounded-xl py-2 text-sm font-bold disabled:opacity-40"
        >
          {resettingSettings ? "実行中…" : "設定を初期化する"}
        </button>
      </div>

      <div className="bg-white border border-line rounded-xl p-3">
        <div className="flex items-center gap-2 mb-1.5">
          <Trash2 size={14} className="text-ink/50" />
          <p className="text-sm font-bold">取得済みデータを全削除</p>
        </div>
        <p className="text-[11px] text-ink/40 mb-3">
          取得済みの投稿データ（投稿本体・出品者情報・価格履歴・削除履歴・☆監視）が全て削除されます。設定は残ります。
        </p>
        <div className="flex items-start gap-1.5 bg-alert/5 border border-alert/20 rounded-lg px-2.5 py-2 mb-3">
          <AlertTriangle size={13} className="text-alert shrink-0 mt-0.5" />
          <p className="text-[11px] text-alert">
            ☆で監視中の投稿も含め、全ての投稿データが削除されます。
          </p>
        </div>
        <button
          onClick={handleDeleteAllScrapedData}
          disabled={deletingData}
          className="w-full bg-alert text-white rounded-xl py-2 text-sm font-bold disabled:opacity-40"
        >
          {deletingData ? "実行中…" : "取得済みデータを全削除する"}
        </button>
      </div>
    </div>
  );
}
