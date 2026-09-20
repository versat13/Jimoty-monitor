import { Ban } from "lucide-react";

/**
 * 価格を表示用文字列に変換する。
 * null/undefined は「価格応談」、0円は「無料」として扱う。
 */
export function formatPrice(price) {
  if (price === null || price === undefined) return "価格応談";
  if (price === 0) return "無料";
  return `¥${price.toLocaleString()}`;
}

/** テーブル等、短い表示幅向けの簡易版 (「価格応談」ではなく「―」)。 */
export function formatPriceCompact(price) {
  if (price === null || price === undefined) return "―";
  if (price === 0) return "無料";
  return `¥${price.toLocaleString()}`;
}

/**
 * 非表示理由のフラグ→ラベル対応。
 *
 * 2026-08-26: ArticleCard/ArticleRow/ArticleDetailPageの3箇所に
 * 同じ内容が重複定義されていたため、このファイルに一本化した。
 */
export const HIDDEN_REASON_LABEL = {
  is_hidden_by_keyword: "NGワード",
  is_hidden_by_category: "NGカテゴリ",
  is_hidden_by_seller_rule: "NGユーザー",
};

export function getHiddenReasons(article) {
  return Object.entries(HIDDEN_REASON_LABEL)
    .filter(([key]) => article[key])
    .map(([, label]) => label);
}

/**
 * DBの日時文字列 (SQLiteのdatetime('now')はUTCで保存される) を
 * 日本時間 (JST, UTC+9) の表示用文字列に変換する。
 *
 * 2026-08-26: 「初回確認: 2026-08-26 03:19」のような表示が実際の
 * 日本時間より9時間遅れて見える、というフィードバックへの対応。
 * DB側の保存形式(UTC)は変更せず、表示時にJSTへ変換する方式を採用した
 * (将来的な多言語対応やデータの一貫性を考慮した判断)。
 *
 * SQLiteのdatetime('now')は "YYYY-MM-DD HH:MM:SS" 形式 (タイムゾーン
 * 情報を含まない、暗黙にUTC) で返るため、末尾に "Z" を付けてから
 * Dateに渡すことでUTCとして解釈させている。
 *
 * @param {string|null|undefined} raw - "YYYY-MM-DD HH:MM:SS" 形式の文字列
 * @param {object} [options]
 * @param {boolean} [options.withTime=true] - 時刻まで表示するか
 * @returns {string} "YYYY-MM-DD HH:MM" (JST) 形式の文字列。rawがnullなら "―"
 */
export function formatDateTimeJST(raw, { withTime = true } = {}) {
  if (!raw) return "―";
  // "YYYY-MM-DD HH:MM:SS" -> ISO 8601のUTCとして解釈させる
  const iso = raw.includes("T") ? raw : raw.replace(" ", "T") + "Z";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return raw; // パース失敗時は元の文字列をそのまま表示

  const pad = (n) => String(n).padStart(2, "0");
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  if (!withTime) return `${y}-${m}-${d}`;

  const hh = pad(date.getHours());
  const mm = pad(date.getMinutes());
  return `${y}-${m}-${d} ${hh}:${mm}`;
}

/**
 * 投稿の作成日時・更新日時 (DetailArticle.history_datetimes 由来、
 * DBの created_datetime / updated_datetime 列) を日本語表記に変換する。
 *
 * 2026-08-27: この日時はジモティーの個別ページ本文に実際に表示されている
 * 「作成2026年8月22日 17:42」のような表記をパースしたものであり、
 * 既に日本時間として書かれている (formatDateTimeJST が対象とする
 * first_seen_at/last_seen_at のような、SQLiteのdatetime('now')が返す
 * UTCの内部管理用タイムスタンプとは性質が異なる)。そのため
 * このタイムゾーン変換は行わず、そのままフォーマットするだけでよい。
 *
 * @param {string|null|undefined} raw - ISO 8601形式の文字列 (Python side の isoformat())
 * @returns {string|null} "2026年8月27日 12:17" 形式。rawがnullならnull
 */
export function formatJapaneseDateTime(raw) {
  if (!raw) return null;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;

  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}

/**
 * DBの内部管理用タイムスタンプ (first_seen_at/last_seen_at、UTC保存) を
 * formatJapaneseDateTime と同じ表記フォーマットに揃えつつJST変換する。
 *
 * 2026-08-27: 「初回確認」「最終確認」の表記を、投稿の「作成」「更新」
 * 表記と同じフォーマット("2026年8月27日 12:17")に統一したいという
 * ユーザー要望への対応。
 */
export function formatJapaneseDateTimeFromUTC(raw) {
  if (!raw) return null;
  const iso = raw.includes("T") ? raw : raw.replace(" ", "T") + "Z";
  return formatJapaneseDateTime(iso);
}

/** NGボタン用のアイコン (☆=WatchButtonと対になる🚫アイコン)。 */
export const NgIcon = Ban;

/**
 * 「大カテゴリ>ジャンル>サブジャンル」形式の表示用文字列を組み立てる
 * (2026-09-08新設)。
 *
 * article.category_name はサブジャンル (またはサブジャンル未指定なら
 * ジャンル自体) を指し、category_mid_name はジャンル、
 * category_parent_nameは大カテゴリを指す (2026-09-08のcategory_filter
 * 階層バグ修正で意味が確定した)。
 *
 * 大カテゴリのみ判明している場合は「大カテゴリ」、大カテゴリ+ジャンル
 * (サブジャンル未指定) の場合は category_mid_name が無いのでその場合は
 * category_nameとcategory_parent_nameのみで組み立てる。
 */
export function formatCategoryHierarchy(article) {
  const parts = [];
  if (article.category_parent_name) parts.push(article.category_parent_name);
  if (article.category_mid_name) parts.push(article.category_mid_name);
  // category_nameは常に「今分かっている最も詳細なカテゴリ」を指すため、
  // category_parent_name/category_mid_nameと重複しない限り追加する。
  if (
    article.category_name &&
    article.category_name !== article.category_parent_name &&
    article.category_name !== article.category_mid_name
  ) {
    parts.push(article.category_name);
  }
  if (parts.length === 0) return "未分類";
  return parts.join(" > ");
}
