import { useState, useEffect, useCallback } from "react";
import { Trash2 } from "lucide-react";
import { api } from "../../api/client";

/**
 * 保存期間切れで削除された投稿の履歴一覧 (2026-09-14新設)。
 *
 * repository.article_repository.purge_expired_articles() が投稿を
 * 削除する際に残すスナップショット (deleted_articles_log) を表示する。
 * この履歴自体も保存期間を過ぎると自動的に削除されるため
 * (「自分が消したわけではない投稿の履歴に強い興味はない」という
 * ユーザーの方針)、ここに表示されるのは「まだ保存期間内の削除履歴」
 * のみになる。
 */
export default function DeletedArticlesLog() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getDeletedArticlesLog()
      .then(setLogs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return (
    <div>
      <p className="text-xs text-ink/50 mb-4">
        保存期間が過ぎて自動的に削除された投稿の履歴です。この履歴自体も保存期間（設定「巡回設定」→「取得範囲」参照）を過ぎると自動的に消えます。
      </p>

      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      {loading && <p className="text-center text-ink/30 text-sm py-8">読み込み中…</p>}

      {!loading && logs.length === 0 && (
        <p className="text-center text-ink/30 text-sm py-8">削除履歴はありません</p>
      )}

      {!loading && logs.length > 0 && (
        <div className="flex flex-col gap-2">
          {logs.map((log) => (
            <a
              key={`${log.article_id}-${log.deleted_at}`}
              href={log.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex gap-3 bg-white border border-line rounded-xl p-3 hover:bg-paper/60"
            >
              {log.thumbnail_url ? (
                <img
                  src={log.thumbnail_url}
                  alt=""
                  className="w-14 h-14 object-cover rounded-lg shrink-0 opacity-60"
                />
              ) : (
                <div className="w-14 h-14 rounded-lg bg-line/50 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate text-ink/70">{log.list_title}</p>
                <p className="text-xs text-ink/40 mt-0.5">
                  {log.price != null ? `${log.price.toLocaleString()}円` : "価格不明"}
                  {log.area_name && ` ・ ${log.area_name}`}
                </p>
                <p className="text-[11px] text-ink/30 mt-1 flex items-center gap-1">
                  <Trash2 size={11} />
                  {new Date(log.deleted_at).toLocaleString("ja-JP")} に削除
                </p>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
