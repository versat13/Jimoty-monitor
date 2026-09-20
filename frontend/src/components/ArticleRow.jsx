import { ShieldAlert, Search, Loader2, RotateCcw, CheckCircle2 } from "lucide-react";
import WatchButton from "./WatchButton";
import NgButton from "./NgButton";
import PriceChangeBadge from "./PriceChangeBadge";
import RangeUncertainBadge from "./RangeUncertainBadge";
import { useMissingArticleConfirm } from "../hooks/useMissingArticleConfirm";
import { formatPriceCompact, getHiddenReasons, formatCategoryHierarchy } from "../utils/articleDisplay";
import { THUMBNAIL_SIZE_PX } from "../utils/articleListConfig";

// 2026-08-26: 出品者情報への導線がリストモードにだけ欠落していた
// (カード/テーブルには出品者名クリックでSellerPanelを開く導線があった)。
// 出品者アイコンボタンを追加して統一した。
//
// 2026-09-05: 表モードとの一貫性のため以下2点を変更した。
//   - 監視(☆)・NG(🚫)ボタンをサムネイル直後 (左寄せ) に移動。
//     以前は右端に置いていたが、表モードでは左側の固定列として
//     配置されており、モードによってボタン位置が真逆になっていた。
//   - 価格の右隣に出品者名のテキストを追加 (表モードで「価格の右に
//     出品者列」を配置したのに合わせる)。
//
// 2026-09-05 追記: 出品者名テキスト自体がボタンとして機能しているため、
// 隣に置いていた重複のユーザーアイコンボタンは削除した (同じ操作を
// 2つのボタンで提供していたのは冗長という指摘への対応)。
//
// 2026-09-05 追記2: サムネイル・監視/NGボタン・タイトルの間の余白が
// 不要に広いという指摘を受け、gapを縮小した。隠れ理由アイコンは
// タイトル脇の独立要素だったのをやめ、サムネイルの右上に小さく
// 重ねるバッジ形式に変更した (テーブルモードと同じ扱いに統一)。
//
// 2026-09-05 追記3: サムネイルサイズ (小/中/大) を選べるようにした
// (thumbnailSize props、共通ヘッダーから渡される)。
//
// 2026-09-11変更: 「終了」タブ再設計により、isMissingTab=trueのとき
// サムネイル左上に「監視範囲外」ラベル、右端に再確認ボタンを追加
// 表示する (ユーザーとの合意事項: 「終了」タブも他タブと同じ
// 表示ルールにする)。
export default function ArticleRow({
  article,
  onOpenSeller,
  onOpenArticle,
  onWatchChange,
  thumbnailSize = "small",
  isMissingTab = false,
  onConfirmed,
}) {
  const hiddenReasons = getHiddenReasons(article);
  const isHidden = hiddenReasons.length > 0;
  const thumbnailPx = THUMBNAIL_SIZE_PX[thumbnailSize] ?? THUMBNAIL_SIZE_PX.small;

  // 2026-09-08追加: PR枠(is_pr_slot)を視覚的に区別する。
  // 既存の border-b (下線) と共存させ、四辺を囲うレイアウト変更は
  // 避けるため、左端にアクセントバーを足すだけに留める
  // (打ち合わせでレイアウト崩れリスクを最小化する方針に決定)。
  const isPrSlot = Boolean(article.is_pr_slot);
  const { confirming, confirmResult, handleConfirm } =
    useMissingArticleConfirm(article, onConfirmed);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpenArticle?.(article)}
      onKeyDown={(e) => e.key === "Enter" && onOpenArticle?.(article)}
      className={`w-full flex items-center gap-1.5 bg-white border-b border-line px-2 py-1.5 text-left cursor-pointer hover:bg-paper/60 ${
        isHidden ? "opacity-50" : ""
      } ${isPrSlot ? "border-l-4 border-l-yellow-400" : ""}`}
    >
      <div
        className="shrink-0 rounded-lg bg-line overflow-hidden relative"
        style={{ width: thumbnailPx, height: thumbnailPx }}
      >
        {article.thumbnail_url ? (
          <img
            src={article.thumbnail_url}
            alt=""
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-ink/20 text-[9px]">
            No Image
          </div>
        )}
        {isHidden && (
          <ShieldAlert
            size={12}
            className="absolute -top-1 -right-1 text-alert bg-white rounded-full"
          />
        )}
      </div>

      <div className="flex items-center gap-0.5 shrink-0">
        <WatchButton
          articleId={article.article_id}
          isWatched={article.is_watched}
          onChange={(v) => onWatchChange?.(article.article_id, v)}
          size={16}
        />
        <NgButton article={article} size={16} />
      </div>

      <div className="flex-1 min-w-0 ml-1">
        <p className="text-sm font-medium truncate">
          {article.full_title || article.list_title}
        </p>
        <p className="text-xs text-ink/40 truncate" title={formatCategoryHierarchy(article)}>
          {formatCategoryHierarchy(article)}
          {article.area_name && ` ・ ${article.area_name}`}
        </p>
        {isMissingTab && (
          <div className="flex items-center gap-1 mt-0.5">
            <RangeUncertainBadge missingKind={article.missing_kind} />
            {confirmResult === "restored" && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-indigo font-medium">
                <RotateCcw size={10} />
                受付中でした
              </span>
            )}
            {confirmResult === "closed" && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-ink/40 font-medium">
                <CheckCircle2 size={10} />
                終了確認済み
              </span>
            )}
          </div>
        )}
      </div>

      {/*
        2026-09-05: 価格・出品者名が横並び1行だと、価格の桁数や
        出品者名の長さによって全体の見た目が揃わない (ユーザー指摘)。
        右寄せ・縦積み (上:価格、下:出品者名) に変更し、右端が常に
        揃うようにした。
      */}
      <div className="flex flex-col items-end shrink-0 ml-1 gap-0.5">
        <span className="font-mono font-bold text-clay text-sm">
          {formatPriceCompact(article.price)}
        </span>
        <PriceChangeBadge count={article.price_change_count} />
        {article.seller_id ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onOpenSeller?.(article.seller_id);
            }}
            className="text-xs text-indigo truncate max-w-[6rem] hover:underline"
          >
            {article.seller_name || "出品者"}
          </button>
        ) : (
          <span className="text-xs text-ink/30">―</span>
        )}
        {isMissingTab && !confirmResult && (
          <button
            onClick={handleConfirm}
            disabled={confirming}
            title="個別ページへアクセスして、まだ受付中か本当に終了したか確認する"
            className="flex items-center gap-0.5 text-[10px] font-bold text-indigo border border-indigo/30 rounded-full px-1.5 py-0.5 disabled:opacity-50"
          >
            {confirming ? <Loader2 size={10} className="animate-spin" /> : <Search size={10} />}
            確認
          </button>
        )}
      </div>
    </div>
  );
}
