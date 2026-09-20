/*
 * 2026-09-15変更 (本番運用対応、ユーザーとの合意事項):
 *
 * 従来は BASE_URL = "http://localhost:8000/api" と固定していたが、
 * これだと以下のケースで正しく動作しない。
 *
 *   - 本番運用 (uvicornが frontend/dist/ の静的ファイルとAPIを
 *     同一オリジンで配信する構成、api/main.py 参照) で、LAN内の
 *     他端末 (スマホ等) から http://<このPCのIPアドレス>:8000 で
 *     アクセスした場合。"localhost" 固定だと、スマホ側から見れば
 *     "localhost" はスマホ自身を指してしまい、APIに繋がらない。
 *
 * このため、開発時 (Vite開発サーバー、デフォルト5173番ポート) と
 * 本番時 (uvicornが直接配信、開発サーバーを介さない) を
 * `import.meta.env.DEV` (Viteが自動的に注入する、開発サーバー起動時は
 * true・本番ビルド後はfalseになる定数) で判定し、
 *   - 開発時: 引き続き "http://localhost:8000/api" を明示的に指定する
 *     (Vite開発サーバー(5173番)とAPIサーバー(8000番)はポートが異なる
 *     別オリジンのため、絶対URLで明示する必要がある)。
 *   - 本番時: 相対パス "/api" のみを使う (uvicornが画面もAPIも同じ
 *     オリジン・ポートで配信するため、アクセスしたホスト名・IPが
 *     そのままAPIの宛先にもなる)。
 */
const BASE_URL = import.meta.env.DEV ? "http://localhost:8000/api" : "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `リクエストに失敗しました (${res.status})`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // 投稿
  listArticles: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/articles${qs ? `?${qs}` : ""}`);
  },
  getArticle: (articleId) => request(`/articles/${articleId}`),
  getPriceHistory: (articleId) => request(`/articles/${articleId}/price-history`),
  getDeletedArticlesLog: () => request("/articles-deleted-log"),
  // 「公開終了」タブの投稿を個別に確認する (2026-09-04 新設)。
  // まだ受付中(restored)ならarticle_statusがactiveに戻る。
  // 本当に終了(deleted)なら投稿自体が削除される。
  confirmArticleStatus: (articleId) =>
    request(`/articles/${articleId}/confirm-status`, { method: "POST" }),

  // 出品者
  getSeller: (sellerId) => request(`/sellers/${sellerId}`),
  getSellerArticles: (sellerId) => request(`/sellers/${sellerId}/articles`),
  // 公式プロフィールページの投稿一覧 (2026-09-04 新設)。
  // getSellerArticles (監視ツールが偶然検知した投稿のみ) とは別物。
  // プロフィール未取得の出品者では空配列が返る。
  getSellerOtherArticles: (sellerId) => request(`/sellers/${sellerId}/other-articles`),
  // プロフィールページを取得しDBを更新する。常に取得する
  // (「続きを読む」＝未取得時のみ／「更新」＝常に、の使い分けは
  // 呼び出し元のSellerPanel.jsxがprofile_fetched_atを見て判断する)。
  fetchSellerProfile: (sellerId) =>
    request(`/sellers/${sellerId}/fetch-profile`, { method: "POST" }),

  // NGワード
  listNgKeywords: () => request("/ng-keywords"),
  createNgKeyword: (keyword) =>
    request("/ng-keywords", { method: "POST", body: JSON.stringify({ keyword }) }),
  toggleNgKeyword: (id) => request(`/ng-keywords/${id}/toggle`, { method: "PATCH" }),
  deleteNgKeyword: (id) => request(`/ng-keywords/${id}`, { method: "DELETE" }),

  // NGカテゴリ
  listNgCategories: () => request("/ng-categories"),
  createNgCategory: (categoryId, categoryName, categoryLevel = "leaf") =>
    request("/ng-categories", {
      method: "POST",
      body: JSON.stringify({
        category_id: categoryId,
        category_name: categoryName,
        category_level: categoryLevel,
      }),
    }),
  deleteNgCategory: (id) => request(`/ng-categories/${id}`, { method: "DELETE" }),
  // 実際にDBへ保存された投稿から出現済みのカテゴリID一覧を返す
  // (2026-09-04新設)。NGカテゴリ登録の手打ち入力を補助するサジェスト用。
  listUsedCategories: () => request("/categories/used"),

  // 出品者ルール（NG／監視）
  listSellerRules: (ruleType = "all") => request(`/seller-rules?rule_type=${ruleType}`),
  // 指定出品者の現在の登録状態を1件取得する (未登録ならnull)。
  // 2026-09-04新設。出品者パネルのNG/監視ボタンの状態表示に使う。
  getSellerRule: (sellerId) => request(`/sellers/${sellerId}/rule`),
  createSellerRule: (payload) =>
    request("/seller-rules", { method: "POST", body: JSON.stringify(payload) }),
  deleteSellerRule: (id) => request(`/seller-rules/${id}`, { method: "DELETE" }),

  // ウォッチリスト（投稿単位）
  watchArticle: (articleId, memo = null) =>
    request(`/articles/${articleId}/watch`, {
      method: "PUT",
      body: JSON.stringify({ memo }),
    }),
  unwatchArticle: (articleId) =>
    request(`/articles/${articleId}/watch`, { method: "DELETE" }),
  clearWatches: (articleIds = null) =>
    request("/watches/clear", {
      method: "POST",
      body: JSON.stringify({ article_ids: articleIds }),
    }),

  // 巡回実行
  triggerScan: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/scan${qs ? `?${qs}` : ""}`, { method: "POST" });
  },

  // 巡回状態 (2026-09-10新設)。手動・自動を問わず「今スキャン中か」
  // 「前回いつ完了したか」「次回自動更新はいつ頃か」を返す。
  // BottomNav付近の更新インジケーターがこれをポーリングする。
  getScanStatus: () => request("/scan-status"),
  // 実行中の巡回 (手動・自動いずれも) に緊急停止を要求する (2026-09-10新設)。
  cancelScan: () => request("/scan/cancel", { method: "POST" }),

  // 取得範囲設定 (ページ数 or 過去n日、排他選択。2026-09-07 新設)
  getScanRangeSettings: () => request("/settings/scan-range"),
  updateScanRangeSettings: (payload) =>
    request("/settings/scan-range", { method: "PUT", body: JSON.stringify(payload) }),

  // 自動更新間隔 (2026-09-08 新設。取得範囲とは別エンドポイントに分離。
  // 理由は api/main.py の update_auto_scan_interval_endpoint 参照)
  updateAutoScanInterval: (autoScanIntervalMinutes) =>
    request("/settings/auto-scan-interval", {
      method: "PUT",
      body: JSON.stringify({ auto_scan_interval_minutes: autoScanIntervalMinutes }),
    }),

  // 監視対象の地域設定 (都道府県・市区町村。2026-09-10 新設)
  getRegionSettings: () => request("/settings/region"),
  updateRegionSettings: (payload) =>
    request("/settings/region", { method: "PUT", body: JSON.stringify(payload) }),

  // 市区町村候補の動的取得 (2026-09-12 新設)
  getAreaOptions: (prefecture) =>
    request(`/settings/region/areas?${new URLSearchParams({ prefecture }).toString()}`),
  fetchAreaOptions: (prefecture) =>
    request(`/settings/region/fetch-areas?${new URLSearchParams({ prefecture }).toString()}`, {
      method: "POST",
    }),

  // 保存期間削除の設定 (2026-09-11 新設)
  getRetentionSettings: () => request("/settings/retention"),
  updateRetentionSettings: (payload) =>
    request("/settings/retention", { method: "PUT", body: JSON.stringify(payload) }),

  // 検索ワードでピックアップするフィルタ (2026-09-08 新設)
  // 「検索」タブの恒常保存条件。NGワードとは逆で「一致したものだけ
  // 抽出」する。判定自体はフロントエンドの正規表現エンジンで行う。
  getPickupSearch: () => request("/settings/pickup-search"),
  updatePickupSearch: (payload) =>
    request("/settings/pickup-search", { method: "PUT", body: JSON.stringify(payload) }),

  // Discord Webhook通知の設定 (2026-09-13 新設)
  // 「検索」タブの条件にヒットした新規投稿が見つかったときに
  // Discordへ通知する機能。
  getDiscordNotificationSettings: () => request("/settings/discord-notification"),
  updateDiscordNotificationSettings: (payload) =>
    request("/settings/discord-notification", { method: "PUT", body: JSON.stringify(payload) }),
  testDiscordNotification: () =>
    request("/settings/discord-notification/test", { method: "POST" }),

  // リセット機能 (2026-09-14 新設)
  // 「設定を初期化」と「取得済みデータを全削除」は独立した操作。
  // 両方を実行すれば結果的に全リセット相当になる、という設計方針。
  resetSettings: () => request("/settings/reset-settings", { method: "POST" }),
  deleteAllScrapedData: () => request("/settings/delete-all-scraped-data", { method: "POST" }),

  // 簡易フィルタの検索履歴 (2026-09-08 新設)
  getSearchHistory: () => request("/search-history"),
  addSearchHistory: (query) =>
    request("/search-history", { method: "POST", body: JSON.stringify({ query }) }),
  clearSearchHistory: () => request("/search-history", { method: "DELETE" }),

  // 設定のエクスポート/インポート (2026-09-08 新設)
  // 対象は「すべての設定」(NGワード・NGカテゴリ・監視/NGユーザー・
  // 取得範囲・自動更新間隔・検索タブの条件)。個別設定 (投稿ごとの
  // 監視☆や価格履歴等) は対象外。
  exportSettings: () => request("/settings/export"),
  importSettings: (data) =>
    request("/settings/import", { method: "POST", body: JSON.stringify(data) }),
};
