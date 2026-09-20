import { X } from "lucide-react";
import { useScanStatus } from "../context/ScanStatusContext";
import { formatPrice } from "../utils/articleDisplay";

/**
 * アプリ内トースト通知の表示コンポーネント (2026-09-15新設)。
 *
 * 「検索」タブの条件にヒットした新規投稿が見つかったときに、画面右上
 * (モバイルでは上部いっぱい) にポップアップとして重ねて表示する。
 * 表示対象・発火タイミングの判定はScanStatusContext側が担い、この
 * コンポーネントは渡された toasts をそのまま描画するだけの見た目担当。
 *
 * 通知条件はDiscord通知・ブラウザ通知と共通 (NGでない新規投稿 かつ
 * 検索タブの正規表現にマッチ、ユーザーとの合意事項)。
 *
 * App.jsx側で ScanStatusProvider の内側、かつ他のUIより上のレイヤー
 * (position: fixed) に配置する想定。
 */
export default function ToastContainer() {
  const { toasts, dismissToast } = useScanStatus();

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed top-3 inset-x-3 sm:inset-x-auto sm:right-3 sm:w-80 z-50 flex flex-col gap-2 pointer-events-none"
      aria-live="polite"
    >
      {toasts.map(({ id, article }) => (
        <div
          key={id}
          role="status"
          className="pointer-events-auto bg-white border border-line rounded-card shadow-card overflow-hidden flex items-stretch animate-slide-up"
        >
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-stretch flex-1 min-w-0"
          >
            {article.thumbnail_url ? (
              <img
                src={article.thumbnail_url}
                alt=""
                className="w-16 h-16 object-cover shrink-0 bg-line"
                loading="lazy"
              />
            ) : (
              <div className="w-16 h-16 shrink-0 bg-line flex items-center justify-center text-[10px] text-ink/30">
                No Image
              </div>
            )}
            <div className="flex-1 min-w-0 px-2.5 py-2">
              <p className="text-[10px] text-indigo font-bold mb-0.5">新着（検索条件にヒット）</p>
              <p className="text-xs text-ink/80 line-clamp-2 leading-tight">{article.list_title}</p>
              <p className="text-xs font-bold text-ink/70 mt-0.5">{formatPrice(article.price)}</p>
            </div>
          </a>
          <button
            onClick={() => dismissToast(id)}
            aria-label="通知を閉じる"
            className="shrink-0 px-2 text-ink/30 hover:text-ink/60"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
