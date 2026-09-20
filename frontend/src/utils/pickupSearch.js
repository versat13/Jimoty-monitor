/**
 * 検索ワードでピックアップするフィルタ (2026-09-08 新設) のロジック。
 *
 * 「検索」タブ (恒常保存) と簡易フィルタ (一時的な絞り込み) の
 * どちらからも共通で使う、正規表現ビルダー・マッチ判定を集約する。
 *
 * === 設計メモ ===
 * NGワード (filters/keyword_filter.py, バックエンド) とは役割が逆で、
 * こちらは「一致したものだけを抽出・強調表示する」用途。判定は
 * このファイルの関数を使ってクライアントサイドで行う (バックエンドの
 * 巡回・DB判定ロジックには一切影響しない)。
 *
 * ビルダーの入力欄は「含めたいワード」(OR結合)・「除外したいワード」
 * (否定先読みで除外) の2軸のみ。AND条件 (両方含む、等) が必要な
 * 複雑なケースは生の正規表現欄に直接書いてもらう想定
 * (ユーザーとの打ち合わせで合意した仕様)。
 */

/**
 * 正規表現の特殊文字をエスケープする。
 * 含める/除外ワードはユーザーが入力した「ただの文字列」として扱う
 * ため、そのままRegExpに渡すと意図しない特殊文字 (括弧など) が
 * 悪さをする。ビルダー入力欄はあくまで平文のワード入力を想定。
 */
function escapeRegExp(word) {
  return word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * カンマ・読点区切りの入力文字列をワードの配列に変換する。
 * 空白のみの要素・空要素は除外する。
 */
export function parseWordsInput(text) {
  if (!text) return [];
  return text
    .split(/[,、]/)
    .map((w) => w.trim())
    .filter((w) => w.length > 0);
}

/**
 * 「含めたいワード」「除外したいワード」から正規表現文字列を
 * 組み立てる。
 *
 * - includeWords: OR結合 (いずれか含む)。 (word1|word2|...)
 * - excludeWords: 否定先読みで除外。 ^(?!.*(word1|word2|...))
 * - 両方指定した場合は除外条件を先頭に、含める条件を後ろに繋げる。
 * - 両方空なら空文字を返す (「絞り込みなし」を意味する)。
 *
 * 生成した文字列は生の正規表現欄にそのまま反映され、以後ユーザーが
 * 手直しできる (手直し後はビルダーとの同期が切れる、という前提の
 * UIと組み合わせて使うことを想定)。
 */
export function buildRegexFromWords(includeWords, excludeWords) {
  const include = (includeWords || []).filter((w) => w.trim().length > 0);
  const exclude = (excludeWords || []).filter((w) => w.trim().length > 0);

  if (include.length === 0 && exclude.length === 0) {
    return "";
  }

  const excludePart =
    exclude.length > 0
      ? `^(?!.*(${exclude.map(escapeRegExp).join("|")}))`
      : "";
  const includePart =
    include.length > 0 ? `.*(${include.map(escapeRegExp).join("|")})` : ".*";

  return `${excludePart}${includePart}`;
}

/**
 * 正規表現文字列が有効かどうかを検証する。
 * 空文字は「絞り込みなし」として常に有効扱い。
 */
export function isValidRegex(pattern) {
  if (!pattern) return true;
  try {
    // eslint-disable-next-line no-new
    new RegExp(pattern, "i");
    return true;
  } catch {
    return false;
  }
}

/**
 * 記事が検索条件にマッチするかどうかを判定する。
 *
 * list_title (タイトル) と description_short (一覧の説明文抜粋) の
 * 両方を対象にする (NGワード側の判定範囲に合わせている)。
 * 空文字・不正な正規表現の場合は「絞り込みなし」として常にtrueを
 * 返す (呼び出し元でエラー表示するかは別途)。
 */
export function matchesSearchExpression(article, pattern) {
  if (!pattern) return true;
  if (!isValidRegex(pattern)) return true;

  const re = new RegExp(pattern, "i");
  const haystack = `${article.list_title || ""} ${article.description_short || ""}`;
  return re.test(haystack);
}

/**
 * 記事一覧を検索条件で絞り込む。
 */
export function filterArticlesBySearch(articles, pattern) {
  if (!pattern) return articles;
  return articles.filter((a) => matchesSearchExpression(a, pattern));
}

/**
 * 簡易フィルタ用の単純な部分一致判定 (大小文字を区別しない)。
 * 「検索」タブの正規表現とは異なり、都度リセットされる一時的な
 * 絞り込みのため、複雑な条件は想定せずシンプルな部分一致で十分
 * (ユーザーとの打ち合わせで合意した設計)。
 */
export function matchesQuickSearch(article, query) {
  if (!query || !query.trim()) return true;
  const needle = query.trim().toLowerCase();
  const haystack = `${article.list_title || ""} ${article.description_short || ""}`.toLowerCase();
  return haystack.includes(needle);
}

/** 記事一覧を簡易フィルタ (部分一致) で絞り込む。 */
export function filterArticlesByQuickSearch(articles, query) {
  if (!query || !query.trim()) return articles;
  return articles.filter((a) => matchesQuickSearch(a, query));
}
