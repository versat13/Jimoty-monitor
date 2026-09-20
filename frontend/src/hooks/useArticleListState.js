import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { api } from "../api/client";
import { useScanStatus } from "../context/ScanStatusContext";
import { filterArticlesBySearch, filterArticlesByQuickSearch } from "../utils/pickupSearch";
import {
  MAIN_TABS,
  ARTICLES_PER_PAGE,
  VIEW_MODE_KEY,
  SORT_KEY_KEY,
  CARD_COLUMNS_KEY,
  THUMBNAIL_SIZE_KEY,
  TABLE_COLUMNS_KEY,
  TABLE_WIDTHS_KEY,
  loadVisibleColumns,
  loadColumnWidths,
  sortArticles,
} from "../utils/articleListState";

/**
 * ArticleListPage の state 管理・データ取得・派生値計算をまとめた
 * カスタムフック (ArticleListPage.jsx から分割、2026-09-13)。
 *
 * ページ本体 (ArticleListPage.jsx) はこのフックが返す値をJSXへ
 * 渡すだけの薄い層にし、状態遷移のロジックはここに集約する。
 */
export function useArticleListState() {
  // 2026-09-04: 旧visibility/statusTabの2state構造を1段タブに統合。
  // mainTabの値はMAIN_TABSのvalueと対応し、そこからstatus/visibilityを
  // 導出する (activeMainTab参照)。
  const [mainTab, setMainTab] = useState("visible");
  const [viewMode, setViewMode] = useState(
    () => localStorage.getItem(VIEW_MODE_KEY) || "card"
  );
  const [sortKey, setSortKey] = useState(
    () => localStorage.getItem(SORT_KEY_KEY) || "display_order"
  );
  const [cardColumns, setCardColumns] = useState(
    () => Number(localStorage.getItem(CARD_COLUMNS_KEY)) || 1
  );
  // 2026-09-05新設: リスト・表モード共通のサムネイルサイズ。
  const [thumbnailSize, setThumbnailSize] = useState(
    () => localStorage.getItem(THUMBNAIL_SIZE_KEY) || "small"
  );
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  // 2026-09-10変更: 巡回状態 (scanning/scanResult/scanError相当) は
  // ScanStatusContextに移した。一覧⇔設定間のページ遷移やブラウザの
  // リロードを挟んでも、サーバー側の実行状態がそのまま反映され続ける
  // ようにするため (以前はこのページ内のローカルstateだったため、
  // ページを離れるとUI上「更新が中断された」ように見えていた)。
  const { isScanning: scanning, scanResult, scanError } = useScanStatus();
  const [selectedSellerId, setSelectedSellerId] = useState(null);
  const [clearing, setClearing] = useState(false);
  // 2026-09-05: カテゴリ・価格範囲フィルタを共通ヘッダーに統合し、
  // 全モード (カード/リスト/表) 共通の絞り込みにした。以前はArticleTable
  // (表モード専用のTableFilterBar) だけが持っていた機能。
  // タブ (mainTab) を切り替えたら自動でリセットする方針
  // (併用不可、というユーザーとの合意事項)。
  const [categoryFilter, setCategoryFilter] = useState("");
  const [priceMin, setPriceMin] = useState("");
  const [priceMax, setPriceMax] = useState("");
  // 2026-09-08新設: 「検索」タブの保存済み正規表現条件。タブ選択中の
  // 一覧絞り込みに使う (サーバー側DBに保存されており、次回このツール
  // を開いたときも自動的に復元される)。
  const [pickupSearchExpression, setPickupSearchExpression] = useState("");
  // 2026-09-08新設: 既存タブ (フィルタ/NG/すべて/終了/監視) 共通の
  // 一時的な簡易検索。タブ切り替えでリセットする (changeMainTab参照)。
  // 「検索」タブでは使わない (PickupSearchBuilderの保存条件と役割が
  // 重複するため)。
  const [quickSearchQuery, setQuickSearchQuery] = useState("");
  // 2026-09-08新設: 一覧のページネーション。フィルタ・ソート適用後の
  // 件数を基準に50件区切りで表示する (公式サイトと同じ件数に合わせる、
  // というユーザーとの打ち合わせで合意した仕様)。
  const [currentPage, setCurrentPage] = useState(1);
  // 2026-09-05新設: 表モードの列表示/非表示。以前はTableFilterBar内で
  // 完結していたが、共通ヘッダーに列選択UIを引き上げたのに伴い、
  // 状態自体もこのページで管理するようにした (表モードの時だけ表示)。
  const [visibleColumns, setVisibleColumns] = useState(loadVisibleColumns);
  const [columnWidths, setColumnWidths] = useState(loadColumnWidths);
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const columnMenuRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(TABLE_COLUMNS_KEY, JSON.stringify([...visibleColumns]));
  }, [visibleColumns]);

  useEffect(() => {
    localStorage.setItem(TABLE_WIDTHS_KEY, JSON.stringify(columnWidths));
  }, [columnWidths]);

  useEffect(() => {
    function onClickOutside(e) {
      if (columnMenuRef.current && !columnMenuRef.current.contains(e.target)) {
        setColumnMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const activeMainTab = MAIN_TABS.find((t) => t.value === mainTab) ?? MAIN_TABS[0];
  const isMissingTab = activeMainTab.status === "missing";
  const isPickupSearchTab = Boolean(activeMainTab.isPickupSearchTab);

  // 2026-09-08新設: 「検索」タブを開いたら、保存済みの検索条件を
  // 読み込んで一覧の絞り込みに使う。他タブでは使わない
  // (pickupSearchExpressionは「検索」タブ選択中のみフィルタに効く)。
  useEffect(() => {
    if (!isPickupSearchTab) return;
    api
      .getPickupSearch()
      .then((s) => setPickupSearchExpression(s.search_expression || ""))
      .catch(() => setPickupSearchExpression(""));
  }, [isPickupSearchTab]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const params = { status: activeMainTab.status, visibility: activeMainTab.visibility };
      const data = await api.listArticles(params);
      setArticles(data);
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  }, [activeMainTab.status, activeMainTab.visibility]);

  useEffect(() => {
    load();
  }, [load]);

  // 2026-09-10新設: 巡回 (手動・自動いずれも) が完了したタイミングで
  // 一覧を再読み込みする。以前は手動更新ボタンのハンドラ内で直接
  // load()を呼んでいたが、更新の実行主体をBottomNav
  // (ScanStatusContext) に移したため、「巡回中(true)→巡回中でない
  // (false)」への変化をこのページ側で検知して再読み込みする方式に
  // 変更した。これにより、自動更新がバックグラウンドで完了した
  // 場合も一覧が自動的に最新化される。
  const wasScanningRef = useRef(false);
  useEffect(() => {
    if (wasScanningRef.current && !scanning) {
      load();
    }
    wasScanningRef.current = scanning;
  }, [scanning, load]);

  // 2026-09-08新設: タブ切り替え・ページ切り替え時にスクロール位置を
  // 一番上に戻す。「中途半端に元の位置が残る」という指摘を受け、
  // 一般的なECサイト・一覧サイトの挙動 (ページや条件が変わったら
  // 一覧の先頭から見せる) に合わせた。スムーズスクロールにすることで
  // 「別の一覧に切り替わった」ことが体感的にも伝わるようにしている。
  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const changeMainTab = (value) => {
    setMainTab(value);
    // 2026-09-05: タブ切り替え時にカテゴリ・価格フィルタを自動リセット
    // (併用不可の方針。タブごとに対象の投稿集合が変わるため、古い
    // フィルタ条件を持ち越すと意図しない絞り込みになってしまう)。
    setCategoryFilter("");
    setPriceMin("");
    setPriceMax("");
    // 2026-09-08追加: 簡易検索も同じ理由でタブ切り替え時にリセット。
    setQuickSearchQuery("");
    // 2026-09-08追加: タブ切り替えでページ1に戻す (合意事項)。
    setCurrentPage(1);
    scrollToTop();
  };

  const changeViewMode = (mode) => {
    setViewMode(mode);
    localStorage.setItem(VIEW_MODE_KEY, mode);
  };

  const changeSortKey = (key) => {
    setSortKey(key);
    localStorage.setItem(SORT_KEY_KEY, key);
  };

  const changeCardColumns = (n) => {
    setCardColumns(n);
    localStorage.setItem(CARD_COLUMNS_KEY, String(n));
  };

  const changeThumbnailSize = (size) => {
    setThumbnailSize(size);
    localStorage.setItem(THUMBNAIL_SIZE_KEY, size);
  };

  const toggleColumn = (key) => {
    setVisibleColumns((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  // 2026-09-10変更: 手動更新の実行自体はBottomNavのボタン
  // (ScanStatusContext.triggerManualScan) に移した。このページでは
  // 巡回完了 (isScanning: true→false) を検知して一覧を再読み込み
  // するだけでよい (上のuseEffect参照)。

  // 2026-09-04: 「監視」タブに統合された後も、「すべて解除」は投稿単位の
  // 監視(☆・watchlist)のみを対象とする。監視ユーザー登録
  // (seller_rules.rule_type='watch') は設定画面またはSellerPanelの
  // 「監視解除」ボタンで明示的に管理する設計思想を維持するため、
  // 一括解除の対象には含めない (誤操作で出品者の監視登録まで消えるのを
  // 防ぐ)。ボタンラベルも「投稿の監視をすべて解除」として範囲を明確にする。
  const handleClearWatches = async () => {
    if (!confirm("投稿の監視（☆）をすべて解除します。監視ユーザー登録は解除されません。よろしいですか？")) return;
    setClearing(true);
    try {
      await api.clearWatches();
      await load();
    } finally {
      setClearing(false);
    }
  };

  const handleWatchChange = (articleId, isWatched) => {
    if (mainTab === "watched_all" && !isWatched) {
      // 監視タブで投稿単位の監視(☆)を解除した場合、この投稿の出品者が
      // 監視ユーザーとして別途登録されていなければ一覧から消えるはず。
      // その判定にはseller_rulesの情報が必要でフロント側だけでは
      // 正確に判断できないため、再読み込みして正しい集合に揃える。
      load();
      return;
    }
    setArticles((prev) =>
      prev.map((a) =>
        a.article_id === articleId ? { ...a, is_watched: isWatched } : a
      )
    );
  };

  // 2026-09-11変更: 「終了」タブ再設計に伴い、confirm-statusの結果が
  // "deleted"から"closed"に変わった (削除しなくなった)。
  //   - "closed" (本当に終了していた): 投稿は削除されずmissing_kind=
  //     'confirmed_closed'のまま残るため、一覧からは消さず、返された
  //     最新のarticle (missing_kind等が更新済み) で置き換える。
  //   - "restored" (まだ受付中だった): article_statusがactiveに戻り
  //     「終了」タブの対象外になるため、一覧 (このページのstate)
  //     からは取り除く (「公開中」タブを開けばそこに表示される)。
  const handleArticleConfirmed = (articleId, result, updatedArticle) => {
    if (result === "restored") {
      setArticles((prev) => prev.filter((a) => a.article_id !== articleId));
    } else if (updatedArticle) {
      setArticles((prev) => prev.map((a) => (a.article_id === articleId ? updatedArticle : a)));
    }
  };

  // 2026-09-11変更: 「終了」タブ専用の並び順(sortClosedArticles、
  // missing_since固定)を廃止し、他タブと同じsortArticles(sortKey
  // 選択式)に統一した (「終了」タブ再設計、ユーザーとの合意事項:
  // ソート・表示モード切替もすべて使えるようにする)。
  const sortedArticles = useMemo(
    () => sortArticles(articles, sortKey),
    [articles, sortKey]
  );

  // 2026-09-05新設: カテゴリの選択肢は、現在のタブに表示されている
  // 投稿から動的に生成する (旧TableFilterBar.jsxのロジックを移植)。
  // 「終了」タブではカテゴリ・価格フィルタ自体を出さない。
  const categoryOptions = useMemo(() => {
    const counts = new Map();
    for (const a of sortedArticles) {
      if (a.category_name) counts.set(a.category_name, (counts.get(a.category_name) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [sortedArticles]);

  const hasActiveFilters =
    categoryFilter !== "" || priceMin !== "" || priceMax !== "" || quickSearchQuery !== "";

  const clearFilters = () => {
    setCategoryFilter("");
    setPriceMin("");
    setPriceMax("");
    setQuickSearchQuery("");
  };

  // 2026-09-05新設: カテゴリ・価格フィルタを全モード共通で適用する。
  // 以前は表モード(ArticleTable内)だけの機能だったが、カード・リスト
  // モードでも同じ条件で絞り込めるようにした。
  // 2026-09-08追加: 「検索」タブのときは、保存済みの正規表現条件
  // (pickupSearchExpression) でさらに絞り込む。それ以外のタブでは
  // 簡易検索 (quickSearchQuery) の部分一致でさらに絞り込む。
  // 2026-09-11変更: 「終了」タブも他タブと同様にフィルタ対象にした
  // (「終了」タブ再設計、ユーザーとの合意事項)。
  const filteredArticles = useMemo(() => {
    const categoryAndPriceFiltered = sortedArticles.filter((a) => {
      if (categoryFilter && a.category_name !== categoryFilter) return false;
      if (priceMin !== "" && (a.price ?? -Infinity) < Number(priceMin)) return false;
      if (priceMax !== "" && (a.price ?? Infinity) > Number(priceMax)) return false;
      return true;
    });
    if (isPickupSearchTab) {
      return filterArticlesBySearch(categoryAndPriceFiltered, pickupSearchExpression);
    }
    return filterArticlesByQuickSearch(categoryAndPriceFiltered, quickSearchQuery);
  }, [
    sortedArticles,
    categoryFilter,
    priceMin,
    priceMax,
    isPickupSearchTab,
    pickupSearchExpression,
    quickSearchQuery,
  ]);

  // 2026-09-08新設: 一覧のページネーション (フィルタ・ソート適用後の
  // 件数を基準に50件区切り。公式サイトと合わせた件数、というユーザー
  // との打ち合わせで合意した仕様)。
  const totalPages = Math.max(1, Math.ceil(filteredArticles.length / ARTICLES_PER_PAGE));

  // フィルタ・ソート・タブの変更でfilteredArticlesが変わった際、
  // 今見ているページが範囲外になっていたら1ページ目に戻す
  // (空のページが表示され続けるのを防ぐ)。
  useEffect(() => {
    setCurrentPage((p) => (p > totalPages ? 1 : p));
  }, [totalPages]);

  const pagedArticles = useMemo(() => {
    const start = (currentPage - 1) * ARTICLES_PER_PAGE;
    return filteredArticles.slice(start, start + ARTICLES_PER_PAGE);
  }, [filteredArticles, currentPage]);

  return {
    // タブ
    mainTab,
    activeMainTab,
    isMissingTab,
    isPickupSearchTab,
    changeMainTab,
    // 表示モード
    viewMode,
    changeViewMode,
    sortKey,
    changeSortKey,
    cardColumns,
    changeCardColumns,
    thumbnailSize,
    changeThumbnailSize,
    // データ
    articles,
    loading,
    loadError,
    scanning,
    scanResult,
    scanError,
    load,
    // 出品者パネル
    selectedSellerId,
    setSelectedSellerId,
    // 監視解除
    clearing,
    handleClearWatches,
    handleWatchChange,
    handleArticleConfirmed,
    // フィルタ
    categoryFilter,
    setCategoryFilter,
    priceMin,
    setPriceMin,
    priceMax,
    setPriceMax,
    pickupSearchExpression,
    setPickupSearchExpression,
    quickSearchQuery,
    setQuickSearchQuery,
    hasActiveFilters,
    clearFilters,
    categoryOptions,
    // 列設定 (表モード)
    visibleColumns,
    toggleColumn,
    columnWidths,
    setColumnWidths,
    columnMenuOpen,
    setColumnMenuOpen,
    columnMenuRef,
    // 派生データ・ページネーション
    sortedArticles,
    filteredArticles,
    pagedArticles,
    currentPage,
    setCurrentPage,
    totalPages,
    scrollToTop,
  };
}
