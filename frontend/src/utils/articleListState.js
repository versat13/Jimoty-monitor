import { TABLE_COLUMNS, DEFAULT_VISIBLE_COLUMNS } from "./articleListConfig";

// 2026-09-04 一段化: 従来「公開中/公開終了」(STATUS_TABS) と
// 「表示中/非表示/すべて/監視投稿/監視ユーザー」(VISIBILITY_TABS) の
// 2軸・2段構造だったタブを、1段の単一タブ列に統合した
// (ユーザーからの「新設タブの大枠は邪魔」というフィードバックに対応)。
//
// 各タブは status ('active'|'missing') と visibility の組を1つ持つ。
// 「終了」タブだけ status='missing' で、他は全て status='active'。
// 「監視」タブは投稿単位の監視(watched)と監視ユーザー(watched_sellers)
// を1つにまとめた visibility='watched_all' を使う
// (バックエンド側では従来通り別テーブル・別ライフサイクルのまま、
// 表示だけをORで合成している。設定画面からの管理や☆ボタンでの個別
// 解除など、既存の操作系はそのまま維持する)。
// 2026-09-08: タブの並び順を「フィルタ, 検索, 監視, NG, すべて, 終了」に
// 変更 (ユーザーとの打ち合わせで合意)。「検索」タブは他タブと違い、
// status/visibilityによるAPI側の絞り込みではなく、「フィルタ」タブと
// 同じ取得範囲 (active/visible) に対してフロントエンドで正規表現
// フィルタ (pickup_search) をさらに適用する、という位置づけのため
// isPickupSearchTab フラグを立てている。
export const MAIN_TABS = [
  { value: "visible", label: "フィルタ", status: "active", visibility: "visible" },
  {
    value: "pickup_search",
    label: "検索",
    status: "active",
    visibility: "visible",
    isPickupSearchTab: true,
  },
  { value: "watched_all", label: "監視", status: "active", visibility: "watched_all" },
  { value: "hidden", label: "NG", status: "active", visibility: "hidden" },
  { value: "all", label: "すべて", status: "active", visibility: "all" },
  { value: "missing", label: "終了", status: "missing", visibility: "all" },
];

// 2026-09-08新設: 一覧のページネーション単位。公式サイトと同じ50件
// 区切りに合わせる (ユーザーとの打ち合わせで合意)。
export const ARTICLES_PER_PAGE = 50;

// ソートキーは3モード共通。「公式順」が既定 (2026-08-24 合意事項)。
export const SORT_OPTIONS = [
  { value: "display_order", label: "公式順（おすすめ順）" },
  { value: "last_seen_at", label: "最終確認が新しい順" },
  { value: "price_asc", label: "価格が安い順" },
  { value: "price_desc", label: "価格が高い順" },
];

export const CARD_COLUMN_OPTIONS = [1, 2, 4, 6, 8];

export const VIEW_MODE_KEY = "jimoty-monitor:view-mode";
export const SORT_KEY_KEY = "jimoty-monitor:sort";
export const CARD_COLUMNS_KEY = "jimoty-monitor:card-columns";
export const THUMBNAIL_SIZE_KEY = "jimoty-monitor:thumbnail-size";
export const TABLE_COLUMNS_KEY = "jimoty-monitor:table-columns";
export const TABLE_WIDTHS_KEY = "jimoty-monitor:table-widths";

export function loadVisibleColumns() {
  try {
    const raw = localStorage.getItem(TABLE_COLUMNS_KEY);
    if (!raw) return DEFAULT_VISIBLE_COLUMNS;
    return new Set(JSON.parse(raw));
  } catch {
    return DEFAULT_VISIBLE_COLUMNS;
  }
}

export function loadColumnWidths() {
  const defaults = Object.fromEntries(TABLE_COLUMNS.map((c) => [c.key, c.defaultWidth]));
  try {
    const raw = localStorage.getItem(TABLE_WIDTHS_KEY);
    if (!raw) return defaults;
    return { ...defaults, ...JSON.parse(raw) };
  } catch {
    return defaults;
  }
}

export function sortArticles(articles, sortKey) {
  const copy = [...articles];
  switch (sortKey) {
    case "last_seen_at":
      copy.sort((a, b) => (a.last_seen_at < b.last_seen_at ? 1 : -1));
      break;
    case "price_asc":
      copy.sort((a, b) => (a.price ?? Infinity) - (b.price ?? Infinity));
      break;
    case "price_desc":
      copy.sort((a, b) => (b.price ?? -Infinity) - (a.price ?? -Infinity));
      break;
    case "display_order":
    default:
      copy.sort((a, b) => {
        const ao = a.display_order ?? Infinity;
        const bo = b.display_order ?? Infinity;
        return ao - bo;
      });
      break;
  }
  return copy;
}

// 2026-09-11削除: 「公開終了」タブ専用の並び順(sortClosedArticles)は
// 「終了」タブ再設計に伴い廃止した。他タブと同じsortArticles
// (sortKey選択式)に統一している (ユーザーとの合意事項)。
