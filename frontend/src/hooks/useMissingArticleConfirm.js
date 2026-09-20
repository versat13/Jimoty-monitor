import { useState } from "react";
import { api } from "../api/client";

/*
 * 2026-09-11新設。
 * 「終了」タブ再設計に伴い、ClosedArticleCard専用だった「確認」ボタンの
 * ロジックを、カード/リスト/表の3表示モード共通で使えるフックに切り出した。
 *
 * 呼び出し側は confirming/confirmError/confirmResult を見て、ボタンの
 * 見た目 (回転アイコン・エラー表示・確認結果メッセージ) を組み立てる。
 */
export function useMissingArticleConfirm(article, onConfirmed) {
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState(null);
  const [confirmResult, setConfirmResult] = useState(null); // "restored" | "closed" | null

  const handleConfirm = async (e) => {
    e?.stopPropagation?.();
    setConfirming(true);
    setConfirmError(null);
    try {
      const res = await api.confirmArticleStatus(article.article_id);
      setConfirmResult(res.result);
      onConfirmed?.(article.article_id, res.result, res.article);
    } catch (err) {
      setConfirmError(err.message);
    } finally {
      setConfirming(false);
    }
  };

  return { confirming, confirmError, confirmResult, handleConfirm };
}
