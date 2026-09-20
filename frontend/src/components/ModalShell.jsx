import { useEffect } from "react";
import { X } from "lucide-react";

/**
 * モーダルの共通シェル。
 *
 * 2026-08-26: 出品者情報(SellerPanel)・商品詳細(ArticleDetailModal)・
 * NG登録(NgRegisterModal)の3種類でモーダルを使うことになったため、
 * 「閉じる操作（外側タップ／×ボタン／Escキー）」を統一する目的で
 * 共通シェルとして切り出した。
 *
 * スタック（商品詳細モーダルの中から出品者情報モーダルを開く等）に
 * 対応するため、z-indexは呼び出し元がpropsで指定する
 * (常に固定値だと後から開いたモーダルが下に隠れてしまうため)。
 */
export default function ModalShell({ onClose, children, zIndex = 30, widthClassName = "sm:max-w-sm" }) {
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 flex items-end sm:items-center sm:justify-center"
      style={{ zIndex }}
    >
      <div className="absolute inset-0 bg-ink/40" onClick={onClose} />

      {/*
        2026-08-27: モーダル内のボタン(キャンセル等)をクリックした際、
        Reactのイベント伝播はDOMの見た目上の位置ではなく元のReactツリー
        構造をたどるため、モーダルを開いたカード(一覧のNGボタン等)にまで
        クリックが伝わり、意図せず別のモーダル(投稿詳細)が開いてしまう
        不具合があった。コンテンツラッパー自体でクリック伝播を止めることで、
        個々のモーダル内のボタンにstopPropagationを書き忘れても
        再発しないようにした (NgRegisterModalのキャンセル/登録ボタンで
        発生していた不具合の根本修正)。
      */}
      <div
        onClick={(e) => e.stopPropagation()}
        className={`relative w-full ${widthClassName} bg-paper rounded-t-3xl sm:rounded-card max-h-[85vh] overflow-y-auto animate-slide-up`}
      >
        {children}
      </div>
    </div>
  );
}

/** モーダル共通のヘッダー (タイトル＋×ボタン)。 */
export function ModalHeader({ title, onClose }) {
  return (
    <div className="sticky top-0 bg-paper/95 backdrop-blur flex items-center justify-between px-4 py-3 border-b border-line z-10">
      <h2 className="font-display font-bold text-base">{title}</h2>
      <button onClick={onClose} className="p-1 text-ink/50">
        <X size={20} />
      </button>
    </div>
  );
}
