import { useRef, useCallback } from "react";
import { ShieldAlert, Search, Loader2, RotateCcw, CheckCircle2 } from "lucide-react";
import WatchButton from "./WatchButton";
import NgButton from "./NgButton";
import PriceChangeBadge from "./PriceChangeBadge";
import RangeUncertainBadge from "./RangeUncertainBadge";
import { useMissingArticleConfirm } from "../hooks/useMissingArticleConfirm";
import { useIsDesktop } from "../hooks/useIsDesktop";
import { formatPriceCompact as formatPrice, formatDateTimeJST, formatCategoryHierarchy } from "../utils/articleDisplay";
import { TABLE_COLUMNS as COLUMNS, THUMBNAIL_SIZE_PX } from "../utils/articleListConfig";

// 2026-09-05: 列定義・カテゴリ/価格フィルタ・列表示選択(TableFilterBar)
// はすべて共通ヘッダー (ArticleListPage.jsx) に統合したため撤去した。
// このコンポーネントは articles (既にフィルタ・ソート済み) と
// visibleColumns・columnWidths を受け取って描画するだけの役割にする。
// TableFilterBar.jsxは廃止。

// 「自動幅」= このコンポーネント内で一番長い文字列を測って幅を決める、
// ダブルクリック時の自動調整用の簡易実装。
function measureAutoWidth(articles, key, minWidth) {
  const canvas = measureAutoWidth._canvas || (measureAutoWidth._canvas = document.createElement("canvas"));
  const ctx = canvas.getContext("2d");
  ctx.font = "14px sans-serif";
  let max = minWidth;
  for (const a of articles) {
    let text = "";
    switch (key) {
      case "list_title":
        text = a.full_title || a.list_title || "";
        break;
      case "price":
        text = formatPrice(a.price);
        break;
      case "category_name":
        text = formatCategoryHierarchy(a);
        break;
      case "area_name":
        text = a.area_name || "";
        break;
      case "seller_name":
        text = a.seller_name || "";
        break;
      case "favorite_count":
        text = String(a.favorite_count ?? "");
        break;
      case "last_seen_at":
        text = formatDateTimeJST(a.last_seen_at);
        break;
      default:
        text = "";
    }
    const width = ctx.measureText(text).width + 32; // 左右パディング分
    if (width > max) max = width;
  }
  return Math.min(Math.ceil(max), 400); // 際限なく広がらないよう上限を設ける
}

// 注意: ソート・カテゴリ/価格フィルタは親コンポーネント(ArticleListPage)
// で共通管理しており、このコンポーネントに渡ってくる articles は
// 既にソート・フィルタ済みの配列である (2026-08-24: 3表示モード間で
// ソート順を共通化、2026-09-05: フィルタも全モード共通化)。
export default function ArticleTable({
  articles,
  onOpenSeller,
  onOpenArticle,
  onWatchChange,
  thumbnailSize = "small",
  visibleColumns,
  columnWidths,
  onColumnWidthsChange,
  isMissingTab = false,
  onConfirmed,
}) {
  const isDesktop = useIsDesktop();
  const resizingRef = useRef(null); // { key, startX, startWidth }

  const activeColumns = COLUMNS.filter(
    (col) => col.alwaysOn || visibleColumns.has(col.key)
  );

  const thumbnailPx = THUMBNAIL_SIZE_PX[thumbnailSize] ?? THUMBNAIL_SIZE_PX.small;
  // 2026-09-06: サムネイル+監視/NGボタン列の幅計算。
  //
  // 経緯: 当初は固定pxの見積もり値 (thumbnailPx + 56) だったが、
  // ボタンの実際の描画幅とズレて余白が残った。次に
  // table-layout:fixed 下で列を中身に合わせる慣用テクニック
  // (width: "0.1%" + white-space: nowrap) に変更したが、これは
  // 単一テキストには効くものの、「サムネイル+ボタン」のような
  // flexレイアウトを含む複合コンテンツでは中身の必要幅を正しく
  // 再計算せず、ボタンがサムネイルに重なって表示される不具合が
  // 発生した (ユーザー報告のスクリーンショットで確認)。
  //
  // 対策: table-layout:fixed では列幅を明示的なpx値で与える必要が
  // あるという原則に立ち返り、サムネイルの実サイズ・ボタン2個分の
  // 実測値・gap・セルpaddingを正確に積み上げて算出する。
  // ボタンのサイズ (WatchButton/NgButton の size={14}) はこの
  // コンポーネント内で固定値として指定しているため、ここで得られる
  // 幅は常に実際の描画幅と一致する。
  const BUTTON_ICON_SIZE = 14;
  const BUTTON_GAP = 2; // gap-0.5
  const THUMB_TO_BUTTONS_GAP = 4; // gap-1
  const CELL_PADDING_X = 6; // px-1.5 (左右それぞれ)
  const thumbnailCellWidth =
    thumbnailPx +
    THUMB_TO_BUTTONS_GAP +
    BUTTON_ICON_SIZE * 2 +
    BUTTON_GAP +
    CELL_PADDING_X * 2;

  // --- 列幅ドラッグリサイズ (PCのみ。2026-08-26新設) ---
  const handleResizeStart = useCallback(
    (key, e) => {
      if (!isDesktop) return;
      e.preventDefault();
      resizingRef.current = { key, startX: e.clientX, startWidth: columnWidths[key] };

      const onMouseMove = (moveEvent) => {
        if (!resizingRef.current) return;
        const { key, startX, startWidth } = resizingRef.current;
        const col = COLUMNS.find((c) => c.key === key);
        const delta = moveEvent.clientX - startX;
        const newWidth = Math.max(col.minWidth, startWidth + delta);
        onColumnWidthsChange((prev) => ({ ...prev, [key]: newWidth }));
      };

      const onMouseUp = () => {
        resizingRef.current = null;
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    [isDesktop, columnWidths, onColumnWidthsChange]
  );

  // ダブルクリックで内容に応じた最適幅に自動調整 (PCの一般的な操作感)
  const handleAutoFit = useCallback(
    (key) => {
      const col = COLUMNS.find((c) => c.key === key);
      const width = measureAutoWidth(articles, key, col.minWidth);
      onColumnWidthsChange((prev) => ({ ...prev, [key]: width }));
    },
    [articles, onColumnWidthsChange]
  );

  const renderCell = (a, key) => {
    switch (key) {
      case "list_title":
        return (
          <td key={key} className="px-3 py-2 font-medium overflow-hidden">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="truncate">{a.full_title || a.list_title}</span>
              {isMissingTab && <RangeUncertainBadge missingKind={a.missing_kind} />}
            </div>
          </td>
        );
      case "price":
        return (
          <td key={key} className="px-3 py-2 font-mono font-bold text-clay overflow-hidden">
            <div className="flex items-center gap-1 min-w-0">
              <span className="truncate">{formatPrice(a.price)}</span>
              <PriceChangeBadge count={a.price_change_count} compact />
            </div>
          </td>
        );
      case "category_name":
        return (
          <td key={key} className="px-3 py-2 text-ink/60 truncate" title={formatCategoryHierarchy(a)}>
            {formatCategoryHierarchy(a)}
          </td>
        );
      case "area_name":
        return (
          <td key={key} className="px-3 py-2 text-ink/60 truncate">
            {a.area_name || "―"}
          </td>
        );
      case "seller_name":
        return (
          <td key={key} className="px-3 py-2 truncate">
            {a.seller_id ? (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenSeller?.(a.seller_id);
                }}
                className="text-indigo hover:underline"
              >
                {a.seller_name || "出品者"}
              </button>
            ) : (
              <span className="text-ink/30">―</span>
            )}
          </td>
        );
      case "favorite_count":
        return (
          <td key={key} className="px-3 py-2 text-ink/60 whitespace-nowrap">
            {a.favorite_count ?? "―"}
          </td>
        );
      case "last_seen_at":
        return (
          <td key={key} className="px-3 py-2 text-ink/40 text-xs whitespace-nowrap">
            {formatDateTimeJST(a.last_seen_at)}
          </td>
        );
      default:
        return <td key={key} className="px-3 py-2">―</td>;
    }
  };

  // colgroupで列幅を指定する。PC幅では table-layout:fixed + 明示的な幅で
  // ドラッグリサイズを機能させ、スマホ幅では auto にして内容に応じた
  // 幅 + 横スクロールに委ねる (2026-08-26: PC/スマホで最適な操作が
  // 異なるというユーザー指摘への対応)。
  const tableLayout = isDesktop ? "fixed" : "auto";

  // 2026-09-05: サムネイル・監視/NGボタン・隠れ理由アイコンの3列に
  // それぞれ px-2 のパディングが入っていたため、列境界のたびに余白が
  // 積み重なって見た目に不要な空白が生まれていた (ユーザー指摘)。
  // サムネイルと監視/NGボタンを1つのセルにまとめて横並びにし、
  // パディングの重複を解消した。隠れ理由アイコンは、隠れている時だけ
  // タイトルセルの脇に小さく添えるバッジ形式に変更し、専用列自体を
  // 廃止した (常に空のセルがパディング分だけ幅を取っていたため)。
  //
  // 2026-09-06 根本原因の特定: 上記のパディング調整をすべて行っても
  // なお「監視/NGボタン列の右側に余白が残る」現象が解消しなかった。
  // 原因は、全列 (サムネイル列も含む) に固定幅を指定していたため、
  // 「余white(残りの幅を吸収する列)」が1つも存在しなかったこと。
  // table-layout:fixed は、列幅の合計がテーブル幅(width:100%)に
  // 満たない場合、その差分をブラウザ実装依存の規則でどこかの列に
  // 配分する。多くの環境ではこの「余り」が意図せず最初の列
  // (サムネイル+ボタン列) に配分されてしまい、右側の空白として
  // 見えていた。
  //
  // 対策: タイトル列 (alwaysOn の列) だけ colgroup の col に width を
  // 指定せず、代わりに対応する<td>にmin-widthを設定する。col に
  // width 未指定の列は table-layout:fixed の仕様上「残りの幅を
  // 全て受け取る」役割になるため、余白は常にタイトル列に吸収され、
  // 他の固定幅列 (サムネイル・価格・出品者等) は指定した幅から
  // 一切ずれなくなる。
  const flexColumn = activeColumns.find((c) => c.alwaysOn);

  return (
    <div className="overflow-x-auto border border-line rounded-xl bg-white">
      <table className="text-sm" style={{ tableLayout, width: isDesktop ? "100%" : "max-content" }}>
        {isDesktop && (
          <colgroup>
            <col style={{ width: thumbnailCellWidth }} />
            {activeColumns.map((col) => (
              <col
                key={col.key}
                style={col.key === flexColumn?.key ? undefined : { width: columnWidths[col.key] }}
              />
            ))}
            {isMissingTab && <col style={{ width: 72 }} />}
          </colgroup>
        )}
        <thead>
          <tr className="border-b border-line bg-paper/60">
            <th className="px-1.5 py-2"></th>
            {activeColumns.map((col) => (
              <th
                key={col.key}
                className="relative text-left px-3 py-2 font-bold text-xs text-ink/60 whitespace-nowrap select-none"
              >
                {col.label}
                {/*
                  2026-09-06: flexColumn (タイトル列) は colgroup の col に
                  width を指定せず「残りの幅を吸収する列」にしたため、
                  ドラッグリサイズ・ダブルクリック自動調整の対象からも
                  外す。これらの操作でcolumnWidthsに値をセットしても
                  col側では無視され続けるため、UIとして触れる意味が
                  ないハンドルを出さないようにする。
                */}
                {isDesktop && col.key !== flexColumn?.key && (
                  <div
                    onMouseDown={(e) => handleResizeStart(col.key, e)}
                    onDoubleClick={() => handleAutoFit(col.key)}
                    className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-indigo/30 active:bg-indigo/50"
                    title="ドラッグで幅調整・ダブルクリックで自動調整"
                  />
                )}
              </th>
            ))}
            {isMissingTab && <th className="px-2 py-2"></th>}
          </tr>
        </thead>
        <tbody>
          {articles.map((a) => (
            <ArticleTableRow
              key={a.article_id}
              article={a}
              activeColumns={activeColumns}
              renderCell={renderCell}
              thumbnailPx={thumbnailPx}
              onOpenArticle={onOpenArticle}
              onWatchChange={onWatchChange}
              isMissingTab={isMissingTab}
              onConfirmed={onConfirmed}
            />
          ))}
          {articles.length === 0 && (
            <tr>
              <td
                colSpan={activeColumns.length + 1 + (isMissingTab ? 1 : 0)}
                className="text-center text-ink/30 py-10"
              >
                条件に一致する投稿がありません
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/*
 * 2026-09-11新設。「終了」タブ再設計に伴い、行ごとに確認ボタンの
 * 状態 (confirming/confirmResult) を持つ必要が生じたため、tbody内の
 * 行を独立コンポーネントに切り出した (Reactのフックはmapのループ内で
 * 直接呼べないため)。
 */
function ArticleTableRow({
  article: a,
  activeColumns,
  renderCell,
  thumbnailPx,
  onOpenArticle,
  onWatchChange,
  isMissingTab,
  onConfirmed,
}) {
  const isHidden = a.is_hidden_by_keyword || a.is_hidden_by_category || a.is_hidden_by_seller_rule;
  // 2026-09-08追加: PR枠(is_pr_slot)の視覚的な区別。
  // <table>はTailwindのpreflightでborder-collapseが効いており
  // <tr>自体にborderを付けても描画されないため、確実に表示される
  // よう先頭<td>に左アクセントバーを付ける方式にしている。
  const isPrSlot = Boolean(a.is_pr_slot);
  const { confirming, confirmResult, handleConfirm } = useMissingArticleConfirm(a, onConfirmed);

  return (
    <tr
      onClick={() => onOpenArticle?.(a)}
      className={`border-b border-line last:border-0 hover:bg-paper/60 cursor-pointer ${
        isHidden ? "opacity-50" : ""
      }`}
    >
      <td
        className={`px-1.5 py-1.5 whitespace-nowrap ${
          isPrSlot ? "border-l-4 border-l-yellow-400" : ""
        }`}
      >
        <div className="flex items-center gap-1">
          <div
            className="shrink-0 rounded-lg bg-line overflow-hidden relative"
            style={{ width: thumbnailPx, height: thumbnailPx }}
          >
            {a.thumbnail_url ? (
              <img
                src={a.thumbnail_url}
                alt=""
                className="w-full h-full object-cover"
                loading="lazy"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-[7px] text-ink/20">
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
              articleId={a.article_id}
              isWatched={a.is_watched}
              onChange={(v) => onWatchChange?.(a.article_id, v)}
              size={14}
            />
            <NgButton article={a} size={14} />
          </div>
        </div>
      </td>
      {activeColumns.map((col) => renderCell(a, col.key))}
      {isMissingTab && (
        <td className="px-2 py-1.5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          {confirmResult === "restored" && (
            <span className="inline-flex items-center gap-0.5 text-[10px] text-indigo font-medium">
              <RotateCcw size={10} />
              受付中
            </span>
          )}
          {confirmResult === "closed" && (
            <span className="inline-flex items-center gap-0.5 text-[10px] text-ink/40 font-medium">
              <CheckCircle2 size={10} />
              確認済み
            </span>
          )}
          {!confirmResult && (
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
        </td>
      )}
    </tr>
  );
}
