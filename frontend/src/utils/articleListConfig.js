// 2026-09-05新設: ArticleListPage.jsx と ArticleTable.jsx の両方から
// 参照する定数を切り出したファイル。ArticleTable.jsx が
// ArticleListPage.jsx を直接importすると循環参照になるため、
// 共通定数はこの独立したモジュールに置く。

// テーブルモードの列定義。以前はArticleTable.jsx内にあったが、列の
// 表示/非表示切り替え(旧TableFilterBarの「列」ボタン)を共通ヘッダーに
// 引き上げたのに伴い、定義自体もこちらに移動した。
//
// 2026-09-05: 「出品者列を価格の右隣に固定したい」という要望を受け、
// 定義順=表示順であるこの配列自体の並びを変更した (price の直後に
// seller_name)。列の表示/非表示切り替え機能はそのまま残しており、
// 出品者列を非表示にした場合は単純に次の表示中の列が価格の右に来る
// だけの自然な振る舞いになる。
export const TABLE_COLUMNS = [
  { key: "list_title", label: "タイトル", alwaysOn: true, defaultWidth: 280, minWidth: 120 },
  { key: "price", label: "価格", defaultWidth: 130, minWidth: 70 },
  { key: "seller_name", label: "出品者", defaultWidth: 120, minWidth: 70 },
  { key: "category_name", label: "カテゴリ", defaultWidth: 110, minWidth: 70 },
  { key: "area_name", label: "地域", defaultWidth: 100, minWidth: 60 },
  { key: "favorite_count", label: "お気に入り", defaultWidth: 90, minWidth: 60 },
  { key: "last_seen_at", label: "最終確認", defaultWidth: 140, minWidth: 90 },
];

export const DEFAULT_VISIBLE_COLUMNS = new Set([
  "list_title",
  "price",
  "category_name",
  "area_name",
  "seller_name",
  "last_seen_at",
]);

// 2026-09-05新設: リスト・表モード共通のサムネイルサイズ切り替え。
// カードモードは列数で実質的なサイズが決まる設計のため対象外。
export const THUMBNAIL_SIZE_OPTIONS = [
  { value: "small", label: "小" },
  { value: "medium", label: "中" },
  { value: "large", label: "大" },
];

// px単位の実サイズ。ArticleRow/ArticleTableへpropsで渡す。
export const THUMBNAIL_SIZE_PX = { small: 44, medium: 64, large: 96 };
