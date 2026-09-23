import {
  LayoutGrid,
  List,
  Table2,
  ArrowUpDown,
  Trash2,
  Columns3,
  X,
  Image as ImageIcon,
  Settings,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import PickupSearchBuilder from "./PickupSearchBuilder";
import QuickSearchInput from "./QuickSearchInput";
import LastAndNextScanLabel from "./LastAndNextScanLabel";
import { useIsDesktop } from "../hooks/useIsDesktop";
import { TABLE_COLUMNS, THUMBNAIL_SIZE_OPTIONS } from "../utils/articleListConfig";
import { MAIN_TABS, SORT_OPTIONS, CARD_COLUMN_OPTIONS } from "../utils/articleListState";

const VIEW_MODES = [
  { value: "card", label: "カード", icon: LayoutGrid },
  { value: "list", label: "リスト", icon: List },
  { value: "table", label: "表", icon: Table2 },
];

/**
 * ArticleListPage のヘッダー (タブ・ソート・フィルタ・列選択・表示モード
 * 切替・「検索」タブの正規表現ビルダー) をまとめたコンポーネント
 * (ArticleListPage.jsx から分割、2026-09-13)。
 *
 * ロジック自体は useArticleListState (hooks/useArticleListState.js) に
 * 集約されているため、このコンポーネントは受け取ったstate・
 * ハンドラをそのままUIへ反映するだけの表示専任コンポーネントとする。
 */
export default function ArticleListHeader({ state }) {
  const navigate = useNavigate();
  const isDesktop = useIsDesktop();
  const {
    mainTab,
    changeMainTab,
    isPickupSearchTab,
    scanResult,
    scanError,
    sortKey,
    changeSortKey,
    hasActiveFilters,
    filteredArticles,
    sortedArticles,
    totalPages,
    currentPage,
    clearing,
    handleClearWatches,
    articles,
    viewMode,
    changeViewMode,
    cardColumns,
    changeCardColumns,
    thumbnailSize,
    changeThumbnailSize,
    columnMenuOpen,
    setColumnMenuOpen,
    columnMenuRef,
    visibleColumns,
    toggleColumn,
    categoryFilter,
    setCategoryFilter,
    categoryOptions,
    priceMin,
    setPriceMin,
    priceMax,
    setPriceMax,
    clearFilters,
    quickSearchQuery,
    setQuickSearchQuery,
    setPickupSearchExpression,
  } = state;

  return (
    <header className="sticky top-0 z-10 bg-paper/95 backdrop-blur pt-5 pb-3 border-b border-line -mx-2 px-2 sm:mx-0 sm:px-0">
      <div className="flex items-center justify-between">
        <h1 className="font-display font-black text-xl tracking-tight">
          <a href="/" className="hover:text-indigo transition-colors">
            ジモティー新着監視ツール
          </a>
        </h1>
        <div className="flex items-center gap-2">
          {/*
            2026-09-10変更: 「今すぐ更新」ボタンはBottomNavの左側へ
            移動した (手動・自動を問わず、どのページにいても更新中で
            あることが分かるようにするため。詳細は
            components/BottomNav.jsx のコメント参照)。
            この跡地には「前回いつ更新したか／次回はいつ頃か」を
            表示する (手動・自動は区別しない、というユーザーとの
            合意事項)。
          */}
          <LastAndNextScanLabel />
          {/*
            2026-09-08追加、2026-09-09更新、2026-09-10変更: 自動更新
            頻度などの設定への導線。以前は常に設定画面のトップタブ
            (NGワード) に着地していたが、URLでタブを区別できるように
            なった (App.jsx参照) ため、このボタンからは「自動更新」
            タブへ直接遷移するようにした。
          */}
          <button
            onClick={() => navigate("/settings/auto-refresh")}
            aria-label="自動更新の設定"
            title="自動更新の設定"
            className="flex items-center justify-center text-ink/60 border border-line bg-white p-2 rounded-full hover:bg-paper/60 active:scale-95 transition-transform"
          >
            <Settings size={14} />
          </button>
        </div>
      </div>

      {scanResult && (
        <p className="text-xs text-ink/60 mt-2">
          新規 {scanResult.new_articles}件 ・ 価格変化 {scanResult.price_changed}件
          ・ 通知対象 {scanResult.notified_count}件
          {scanResult.cancelled && " ・ 緊急停止により途中終了"}
        </p>
      )}

      {scanError && <p className="text-xs text-alert mt-2">{scanError}</p>}

      {/*
        2026-09-04: 「公開中/公開終了」「表示中/非表示/…」の2段構造を
        1段のタブ列に統合。MAIN_TABSの定義から自明にstatus/visibility
        両方が決まるため、ここではmainTabの切り替えだけで良い。
      */}
      <div className="flex flex-wrap gap-1 mt-3 bg-line/50 rounded-full p-1">
        {MAIN_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => changeMainTab(tab.value)}
            className={`flex-1 min-w-fit text-xs font-bold py-1.5 px-2 rounded-full transition-colors whitespace-nowrap ${
              mainTab === tab.value
                ? "bg-white text-indigo shadow-sm"
                : "text-ink/40"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/*
        2026-09-11変更: 以前は「終了」タブだけソート・表示モード・
        フィルタ・検索コントロール群を一切出さず、レイアウト自体を
        分けていた。「終了」タブの再設計 (確定終了/監視範囲外の
        区別、ユーザーとの合意事項) により、「終了」タブでも他の
        タブと同じ操作性 (ソート・表示モード切替・カテゴリ/価格
        フィルタ・検索) を提供するようにした。
      */}
      <>
      <div className="flex items-center gap-2 mt-2 flex-wrap">
        <div className="flex items-center gap-1 text-xs">
          <ArrowUpDown size={12} className="text-ink/40" />
          <select
            value={sortKey}
            onChange={(e) => changeSortKey(e.target.value)}
            className="bg-white border border-line rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-indigo/30"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/*
          2026-09-05: 「◯件 / 全◯件」を全モード共通のヘッダーに統合
          (以前は表モード内だけの専用行だった)。カテゴリ・価格フィルタも
          全モード共通になったため、フィルタ適用後の件数
          (filteredArticles) と全体件数 (sortedArticles) を常に併記する。
        */}
        <p className="text-xs text-ink/40">
          {hasActiveFilters
            ? `${filteredArticles.length}件 / 全${sortedArticles.length}件`
            : `${sortedArticles.length}件`}
          {totalPages > 1 && ` （${currentPage}/${totalPages}ページ）`}
        </p>

        {mainTab === "watched_all" && (
          <button
            onClick={handleClearWatches}
            disabled={clearing || articles.length === 0}
            title="投稿単位の監視（☆）のみ解除します。監視ユーザー登録は解除されません"
            className="flex items-center gap-1 text-xs text-alert border border-alert/30 rounded-lg px-2 py-1 disabled:opacity-40"
          >
            <Trash2 size={12} />
            投稿の監視を解除
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          {viewMode === "card" && (
            <div className="flex items-center gap-1 text-xs text-ink/40">
              表示列
              <div className="flex gap-0.5 bg-line/50 rounded-full p-0.5">
                {CARD_COLUMN_OPTIONS.map((n) => (
                  <button
                    key={n}
                    onClick={() => changeCardColumns(n)}
                    className={`w-6 h-6 rounded-full text-xs font-bold transition-colors ${
                      cardColumns === n
                        ? "bg-white text-indigo shadow-sm"
                        : "text-ink/40"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/*
            2026-09-05: 「列の境界をドラッグ〜」の注意書きと「列」
            選択ボタンは表モード固有の要素。以前はサムネイルサイズの
            右側に置いていたが、リストモードからテーブルモードに
            切り替えた際、共通要素であるサムネイルサイズの表示位置が
            ずれて見える (テーブル固有の要素が割り込むことで右詰めの
            基準がずれる) という指摘を受け、表モード固有の要素を先に、
            リスト・テーブル共通のサムネイルサイズを常に一番右寄りに
            配置する順序に変更した。
          */}
          {viewMode === "table" && isDesktop && (
            <p className="text-xs text-ink/30 whitespace-nowrap">
              列の境界をドラッグで幅調整・ダブルクリックで自動調整
            </p>
          )}

          {viewMode === "table" && (
            <div className="relative" ref={columnMenuRef}>
              <button
                onClick={() => setColumnMenuOpen((v) => !v)}
                className="flex items-center gap-1 text-xs text-ink/60 border border-line rounded-lg px-2 py-1.5 bg-white hover:text-indigo"
              >
                <Columns3 size={13} />
                列
              </button>
              {columnMenuOpen && (
                <div className="absolute right-0 mt-1 bg-white border border-line rounded-xl shadow-card p-2 z-10 w-40">
                  {TABLE_COLUMNS.filter((c) => !c.alwaysOn).map((col) => (
                    <label
                      key={col.key}
                      className="flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-paper rounded-lg cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={visibleColumns.has(col.key)}
                        onChange={() => toggleColumn(col.key)}
                        className="accent-indigo"
                      />
                      {col.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          {/*
            2026-09-05新設: リスト・表モード共通のサムネイルサイズ切替。
            カードモードは列数で実質サイズが決まるため対象外。
            常に一番右寄り (表示モード切替ボタンの直前) に置くことで、
            モードを切り替えても位置が変わらないようにしている。
          */}
          {(viewMode === "list" || viewMode === "table") && (
            <div className="flex items-center gap-1 text-xs text-ink/40">
              <ImageIcon size={12} />
              <div className="flex gap-0.5 bg-line/50 rounded-full p-0.5">
                {THUMBNAIL_SIZE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => changeThumbnailSize(opt.value)}
                    className={`px-2 h-6 rounded-full text-xs font-bold transition-colors ${
                      thumbnailSize === opt.value
                        ? "bg-white text-indigo shadow-sm"
                        : "text-ink/40"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex gap-0.5 bg-line/50 rounded-full p-1 shrink-0">
            {VIEW_MODES.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                onClick={() => changeViewMode(value)}
                title={label}
                className={`p-1.5 rounded-full transition-colors ${
                  viewMode === value
                    ? "bg-white text-indigo shadow-sm"
                    : "text-ink/40"
                }`}
              >
                <Icon size={14} />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/*
        2026-09-05新設: カテゴリ・価格範囲フィルタ。以前は表モード
        専用のTableFilterBarにあったが、共通ヘッダーに統合し全モード
        共通にした。タブを切り替えると自動でリセットされる
        (changeMainTab参照)。
        2026-09-08追加: 簡易検索 (QuickSearchInput)。「検索」タブ
        では専用のPickupSearchBuilderが同じ役割を担うため、ここでは
        表示しない (二重に検索欄が並ぶのを避けるため)。
      */}
      <div className="flex flex-wrap items-center gap-2 mt-2">
        {!isPickupSearchTab && (
          <QuickSearchInput value={quickSearchQuery} onChange={setQuickSearchQuery} />
        )}

        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="bg-white border border-line rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo/30"
        >
          <option value="">カテゴリ：すべて</option>
          {categoryOptions.map(([name, count]) => (
            <option key={name} value={name}>
              {name}（{count}）
            </option>
          ))}
        </select>

        <div className="flex items-center gap-1">
          <input
            type="number"
            inputMode="numeric"
            placeholder="下限"
            value={priceMin}
            onChange={(e) => setPriceMin(e.target.value)}
            className="w-20 bg-white border border-line rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo/30"
          />
          <span className="text-ink/30 text-xs">〜</span>
          <input
            type="number"
            inputMode="numeric"
            placeholder="上限"
            value={priceMax}
            onChange={(e) => setPriceMax(e.target.value)}
            className="w-20 bg-white border border-line rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-indigo/30"
          />
          <span className="text-ink/30 text-xs">円</span>
        </div>

        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1 text-xs text-ink/50 hover:text-alert"
          >
            <X size={12} />
            条件をクリア
          </button>
        )}
      </div>
      </>

      {/*
        2026-09-10変更: 「検索」タブの正規表現ビルダーは常に画面上部に
        固定表示してほしい、というユーザーとの合意により、この
        headerの内側 (sticky top-0 の対象内) に移動した。以前は
        <main>側 (一覧の上、スクロール対象) にあったため、一覧を
        スクロールすると検索条件が隠れてしまっていた。
      */}
      {isPickupSearchTab && (
        <div className="mt-2">
          <PickupSearchBuilder onSaved={setPickupSearchExpression} />
        </div>
      )}
    </header>
  );
}
