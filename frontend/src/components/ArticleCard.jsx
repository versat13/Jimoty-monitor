import { MapPin, Heart, ShieldAlert, ExternalLink, Search, Loader2, RotateCcw, CheckCircle2 } from "lucide-react";
import WatchButton from "./WatchButton";
import NgButton from "./NgButton";
import PriceChangeBadge from "./PriceChangeBadge";
import RangeUncertainBadge from "./RangeUncertainBadge";
import { useMissingArticleConfirm } from "../hooks/useMissingArticleConfirm";
import { formatPrice, getHiddenReasons, formatCategoryHierarchy } from "../utils/articleDisplay";

// 2026-08-24: 当初は画像左・テキスト右の横並びレイアウトだったが、
// カード表示を複数列にするユーザー要望に対応するため、画像を上・
// テキストを下に積む縦積みレイアウトに変更した。横並びのままだと
// 列幅が狭くなった際に文字が縦に1文字ずつ折り返される崩れが発生した。
//
// 2026-09-11変更: 「終了」タブ再設計により、以前は専用の
// ClosedArticleCard (モノクロサムネイル・独自レイアウト) を使って
// いたが、このカードに統合した (isMissingTabがtrueのときだけ
// 「監視範囲外」ラベル・再確認ボタンを追加表示する。ユーザーとの
// 合意事項: 「終了」タブも他タブと同じ表示ルールにする)。
export default function ArticleCard({
  article, onOpenSeller, onWatchChange, onOpenArticle, isMissingTab = false, onConfirmed,
}) {
  const hiddenReasons = getHiddenReasons(article);
  const isHidden = hiddenReasons.length > 0;
  // 2026-09-08追加: PR枠(is_pr_slot)の視覚的な区別。
  // カードは独立要素なので四辺の枠線色をそのまま差し替えても
  // レイアウト崩れの心配がない (打ち合わせで確認済み)。
  const isPrSlot = Boolean(article.is_pr_slot);
  const { confirming, confirmError, confirmResult, handleConfirm } =
    useMissingArticleConfirm(article, onConfirmed);

  return (
    <div
      className={`rounded-card bg-white shadow-card overflow-hidden flex flex-col border ${
        isPrSlot ? "border-yellow-400" : "border-line"
      } ${isHidden ? "opacity-60" : ""}`}
    >
      <div
        className="relative aspect-square bg-line cursor-pointer"
        onClick={() => onOpenArticle?.(article)}
      >
        {article.thumbnail_url ? (
          <img
            src={article.thumbnail_url}
            alt=""
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-xs text-ink/30">
            No Image
          </div>
        )}
        {/*
          2026-08-26: ☆(WatchButton)と🚫(NgButton)を常にセットで
          同じ位置に置くルールにした (以前はWatchButtonの置き場所が
          カード/リスト/テーブルでバラバラだったための一貫性改善)。
        */}
        <div className="absolute top-1.5 right-1.5 flex items-center gap-1 bg-white/90 rounded-full px-1.5 py-1 shadow-sm">
          <WatchButton
            articleId={article.article_id}
            isWatched={article.is_watched}
            onChange={(v) => onWatchChange?.(article.article_id, v)}
            size={16}
          />
          <NgButton article={article} size={16} />
        </div>
        {isMissingTab && (
          <div className="absolute top-1.5 left-1.5">
            <RangeUncertainBadge missingKind={article.missing_kind} />
          </div>
        )}
      </div>

      <div
        className="p-3 flex-1 flex flex-col cursor-pointer"
        onClick={() => onOpenArticle?.(article)}
      >
        <h3 className="font-display font-bold text-sm leading-snug line-clamp-2 min-h-[2.5em]">
          {article.full_title || article.list_title}
        </h3>

        <p className="font-mono font-bold text-clay text-lg mt-1">
          {formatPrice(article.price)}
        </p>
        <PriceChangeBadge count={article.price_change_count} className="mt-1 self-start" />

        <div className="flex items-center gap-1 mt-1 text-xs text-ink/60">
          <MapPin size={12} className="shrink-0" />
          <span className="truncate">
            {[article.area_name, article.station_name].filter(Boolean).join(" / ") || "地域不明"}
          </span>
        </div>

        <div className="flex items-center justify-between mt-2 gap-1">
          <span
            className="text-xs px-2 py-0.5 rounded-full bg-indigo/10 text-indigo font-medium truncate"
            title={formatCategoryHierarchy(article)}
          >
            {formatCategoryHierarchy(article)}
          </span>
          {article.favorite_count !== null && article.favorite_count !== undefined && (
            <span className="flex items-center gap-1 text-xs text-ink/50 shrink-0">
              <Heart size={12} />
              {article.favorite_count}
            </span>
          )}
        </div>
      </div>

      {isHidden && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 bg-alert/10 border-t border-alert/20 text-alert text-xs font-medium">
          <ShieldAlert size={13} className="shrink-0" />
          <span className="truncate">非表示: {hiddenReasons.join("・")}</span>
        </div>
      )}

      {isMissingTab && confirmResult && (
        <div
          className={`flex items-center gap-1.5 px-3 py-1.5 border-t text-xs font-medium ${
            confirmResult === "restored"
              ? "bg-indigo/10 border-indigo/20 text-indigo"
              : "bg-line/30 border-line text-ink/50"
          }`}
        >
          {confirmResult === "restored" ? (
            <>
              <RotateCcw size={13} className="shrink-0" />
              まだ受付中でした
            </>
          ) : (
            <>
              <CheckCircle2 size={13} className="shrink-0" />
              終了を確認しました
            </>
          )}
        </div>
      )}
      {isMissingTab && confirmError && (
        <p className="px-3 py-1 text-[11px] text-alert">{confirmError}</p>
      )}

      <div className="flex items-center justify-between px-3 py-2 border-t border-line bg-paper/50 gap-2">
        <button
          onClick={() => onOpenSeller?.(article.seller_id)}
          disabled={!article.seller_id}
          className="text-xs text-indigo font-medium disabled:text-ink/30 disabled:cursor-default truncate"
        >
          {article.seller_name || "出品者情報なし"}
        </button>
        <div className="flex items-center gap-2 shrink-0">
          {isMissingTab && !confirmResult && (
            <button
              onClick={handleConfirm}
              disabled={confirming}
              title="個別ページへアクセスして、まだ受付中か本当に終了したか確認する"
              className="flex items-center gap-1 text-xs font-bold text-indigo border border-indigo/30 rounded-full px-2 py-0.5 disabled:opacity-50"
            >
              {confirming ? <Loader2 size={11} className="animate-spin" /> : <Search size={11} />}
              確認
            </button>
          )}
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-xs text-ink/50 hover:text-indigo shrink-0"
          >
            見る <ExternalLink size={12} />
          </a>
        </div>
      </div>
    </div>
  );
}
