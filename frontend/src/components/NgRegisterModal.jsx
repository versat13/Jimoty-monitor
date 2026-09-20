import { useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "../api/client";
import ModalShell, { ModalHeader } from "./ModalShell";

/**
 * NG登録モーダル (2026-08-26新設)。
 *
 * mode="keyword": 投稿タイトル全文を入力欄の初期値にしておき、
 *   ユーザーがそこから不要な部分を削って必要な語句だけを残し、
 *   登録できるようにする。「全文から削り出す」という操作感を重視した
 *   設計 (ユーザーの要望通り)。
 * mode="seller": 出品者名を確認した上でNGユーザーとして登録するだけの、
 *   入力欄を持たないシンプルな確認モーダル。
 */
export default function NgRegisterModal({ mode, article, onClose }) {
  const [keywordInput, setKeywordInput] = useState(
    mode === "keyword" ? article.full_title || article.list_title || "" : ""
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  const isKeywordMode = mode === "keyword";

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      if (isKeywordMode) {
        const trimmed = keywordInput.trim();
        if (!trimmed) {
          setError("NGワードを入力してください。");
          setSubmitting(false);
          return;
        }
        await api.createNgKeyword(trimmed);
      } else {
        await api.createSellerRule({
          seller_id: article.seller_id,
          seller_name: article.seller_name,
          rule_type: "ng",
        });
      }
      setDone(true);
    } catch (e) {
      setError(e.message || "登録に失敗しました。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell onClose={onClose} zIndex={50} widthClassName="sm:max-w-sm">
      <ModalHeader
        title={isKeywordMode ? "NGワードとして登録" : "この出品者をNG登録"}
        onClose={onClose}
      />

      <div className="px-4 py-4">
        {done ? (
          <div className="text-center py-4">
            <p className="text-sm text-ink/70">登録しました。</p>
            <p className="text-xs text-ink/40 mt-1">
              該当する投稿は「表示中」タブから除外されます（データ自体は取得し続けます）。
            </p>
            <button
              onClick={onClose}
              className="mt-4 bg-indigo text-white rounded-xl px-4 py-2 text-sm font-bold"
            >
              閉じる
            </button>
          </div>
        ) : isKeywordMode ? (
          <>
            <p className="text-xs text-ink/50 mb-2">
              投稿タイトルの全文が入っています。NGにしたい語句だけを残して、
              不要な部分を削ってから登録してください。
            </p>
            <textarea
              value={keywordInput}
              onChange={(e) => setKeywordInput(e.target.value)}
              rows={3}
              className="w-full bg-white border border-line rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30 resize-none"
              autoFocus
            />
          </>
        ) : (
          <p className="text-sm text-ink/70">
            <span className="font-bold">{article.seller_name || "この出品者"}</span>{" "}
            をNGユーザーとして登録します。この出品者の投稿は「表示中」タブから
            除外されます（データ自体は取得し続けます）。
          </p>
        )}

        {error && <p className="text-alert text-xs mt-2">{error}</p>}

        {!done && (
          <div className="flex gap-2 mt-4">
            <button
              onClick={onClose}
              className="flex-1 border border-line rounded-xl py-2 text-sm font-medium text-ink/60"
            >
              キャンセル
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting || (isKeywordMode && !keywordInput.trim())}
              className="flex-1 bg-alert text-white rounded-xl py-2 text-sm font-bold disabled:opacity-50 flex items-center justify-center gap-1.5"
            >
              {submitting && <Loader2 size={14} className="animate-spin" />}
              登録する
            </button>
          </div>
        )}
      </div>
    </ModalShell>
  );
}
