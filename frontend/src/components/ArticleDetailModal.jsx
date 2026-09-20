import { useState, useEffect } from "react";
import {
  MapPin,
  Heart,
  ShieldAlert,
  ExternalLink,
  Loader2,
  TrendingDown,
  TrendingUp,
  Clock,
  Tag,
} from "lucide-react";
import { api } from "../api/client";
import WatchButton from "./WatchButton";
import NgButton from "./NgButton";
import SellerPanel from "./SellerPanel";
import ModalShell, { ModalHeader } from "./ModalShell";
import {
  formatPrice,
  getHiddenReasons,
  formatJapaneseDateTime,
  formatJapaneseDateTimeFromUTC,
  formatCategoryHierarchy,
} from "../utils/articleDisplay";

/**
 * 投稿詳細モーダル。
 *
 * 2026-08-26: 当初は /articles/:id への画面遷移(ArticleDetailPage)
 * だったが、「出品者情報のようにモーダルで見たい」というユーザー要望を
 * 受けてモーダル化した。出品者情報モーダルはこのモーダルの上にさらに
 * 重ねて開く (スタック構造) ため、zIndexを一段高くして渡している。
 *
 * URLroutingとは切り離し、article_idをpropsで受け取る単純なコンポーネント
 * とした (どこから呼び出しても同じ挙動にするため)。
 */
export default function ArticleDetailModal({ articleId, onClose }) {
  const [article, setArticle] = useState(null);
  const [priceHistory, setPriceHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedSellerId, setSelectedSellerId] = useState(null);
  const [descExpanded, setDescExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDescExpanded(false);
    Promise.all([api.getArticle(articleId), api.getPriceHistory(articleId)])
      .then(([a, history]) => {
        if (!cancelled) {
          setArticle(a);
          setPriceHistory(history);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [articleId]);

  const hiddenReasons = article ? getHiddenReasons(article) : [];
  const isHidden = hiddenReasons.length > 0;

  return (
    <>
      <ModalShell onClose={onClose} zIndex={30} widthClassName="sm:max-w-md">
        <ModalHeader title="投稿の詳細" onClose={onClose} />

        {loading && (
          <div className="flex justify-center py-16 text-ink/30">
            <Loader2 size={24} className="animate-spin" />
          </div>
        )}

        {!loading && (error || !article) && (
          <div className="text-alert text-sm bg-alert/10 rounded-xl mx-4 my-4 p-4 text-center">
            {error || "投稿が見つかりませんでした。"}
          </div>
        )}

        {!loading && article && (
          <div className="px-4 py-4">
            <div className="flex items-start justify-between gap-2">
              <div className="rounded-card overflow-hidden bg-line aspect-square flex-1">
                {article.thumbnail_url ? (
                  <img
                    src={article.thumbnail_url}
                    alt=""
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-ink/30 text-sm">
                    No Image
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-start justify-between gap-2 mt-4">
              <h1 className="font-display font-bold text-lg leading-snug flex-1">
                {article.full_title || article.list_title}
              </h1>
              <div className="flex items-center gap-1.5 shrink-0">
                <WatchButton
                  articleId={article.article_id}
                  isWatched={article.is_watched}
                  onChange={(v) => setArticle((prev) => ({ ...prev, is_watched: v }))}
                  size={22}
                />
                <NgButton article={article} size={22} />
              </div>
            </div>

            {isHidden && (
              <div className="flex items-center gap-1.5 mt-3 px-3 py-2 bg-alert/10 rounded-xl text-alert text-xs font-medium">
                <ShieldAlert size={14} className="shrink-0" />
                非表示条件に一致: {hiddenReasons.join("・")}
              </div>
            )}

            {article.is_closed && (
              <div className="mt-3 px-3 py-2 bg-ink/5 rounded-xl text-ink/50 text-xs font-medium text-center">
                この投稿は受付を終了しています
              </div>
            )}

            <p className="font-mono font-bold text-clay text-2xl mt-2">
              {formatPrice(article.price)}
            </p>

            <div className="flex items-center gap-1 mt-2 text-sm text-ink/60">
              <MapPin size={14} />
              <span>
                {[article.prefecture, article.area_name, article.station_name]
                  .filter(Boolean)
                  .join(" / ") || "地域不明"}
              </span>
            </div>

            {/*
              2026-09-09新設: 「大カテゴリ>ジャンル>サブジャンル」の
              階層表示 (ユーザー要望: 「出品地点の下、ハッシュタグの
              上」)。既存のカテゴリバッジ (タグと同じ行、最も詳細な
              カテゴリ1つだけをコンパクトに表示するもの) とは別に、
              階層の全体像が一目で分かる専用行として追加した。
            */}
            <div className="flex items-center gap-1 mt-1.5 text-xs text-ink/50">
              <Tag size={13} className="shrink-0" />
              <span className="truncate">{formatCategoryHierarchy(article)}</span>
            </div>

            <div className="flex items-center justify-between gap-2 mt-3">
              <div className="flex items-center gap-1.5 min-w-0 overflow-x-auto scrollbar-hide">
                <span className="shrink-0 text-xs px-2.5 py-1 rounded-full bg-indigo/10 text-indigo font-medium whitespace-nowrap">
                  {article.category_name || "未分類"}
                </span>
                {article.tags?.map((tag) => (
                  <span
                    key={tag}
                    className="shrink-0 text-xs px-2.5 py-1 rounded-full bg-line text-ink/60 whitespace-nowrap"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
              {article.favorite_count !== null && article.favorite_count !== undefined && (
                <span className="flex items-center gap-1 text-xs text-ink/50 shrink-0">
                  <Heart size={13} />
                  {article.favorite_count}
                </span>
              )}
            </div>

            {/*
              2026-08-27: ジモティー公式にも表示されている「投稿の作成日と
              更新日」を、カテゴリと説明文の間に表示するようにした。
              created_datetime/updated_datetimeは個別ページ本文の
              「作成2026年8月22日 17:42」表記をそのままパースしたもので
              既に日本時間のため、formatJapaneseDateTime (JST変換なし)
              を使う。
            */}
            {(article.created_datetime || article.updated_datetime) && (
              <p className="text-xs text-ink/40 mt-2">
                {article.updated_datetime && (
                  <>更新: {formatJapaneseDateTime(article.updated_datetime)}</>
                )}
                {article.updated_datetime && article.created_datetime && " ／ "}
                {article.created_datetime && (
                  <>作成: {formatJapaneseDateTime(article.created_datetime)}</>
                )}
              </p>
            )}

            {priceHistory.length > 0 && (
              <div className="mt-5">
                <h2 className="font-display font-bold text-sm mb-2 flex items-center gap-1.5">
                  <Clock size={14} className="text-ink/40" />
                  価格の変化
                </h2>
                <div className="bg-white border border-line rounded-xl overflow-hidden">
                  {priceHistory.map((h, i) => {
                    const isDown = (h.new_price ?? 0) < (h.old_price ?? 0);
                    return (
                      <div
                        key={i}
                        className="flex items-center justify-between px-3 py-2 border-b border-line last:border-0 text-sm"
                      >
                        <span className="text-xs text-ink/40">
                          {formatJapaneseDateTimeFromUTC(h.changed_at)}
                        </span>
                        <span className="flex items-center gap-1.5">
                          <span className="text-ink/40 line-through text-xs">
                            {formatPrice(h.old_price)}
                          </span>
                          {isDown ? (
                            <TrendingDown size={13} className="text-indigo" />
                          ) : (
                            <TrendingUp size={13} className="text-alert" />
                          )}
                          <span className="font-mono font-bold text-clay">
                            {formatPrice(h.new_price)}
                          </span>
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {article.description_full && (
              <div className="mt-5">
                <h2 className="font-display font-bold text-sm mb-2">説明文</h2>
                {/*
                  2026-08-27: 本文が長い投稿(実データで確認済み、数百字を
                  超えるものがある)で、モーダルの縦スクロールが際限なく
                  伸びてしまうのを防ぐため、400文字で省略し「続きを読む」
                  で全文表示する挙動を追加した (SellerPanelの自己紹介文と
                  同じ考え方だが、こちらは文字数ベースで判定している。
                  自己紹介文は行数(line-clamp)ベースで、対象読者と
                  想定文章量が異なるため使い分けている)。
                */}
                <p className="text-sm text-ink/70 whitespace-pre-line leading-relaxed bg-white border border-line rounded-xl p-3">
                  {descExpanded || article.description_full.length <= 400
                    ? article.description_full
                    : `${article.description_full.slice(0, 400)}…`}
                </p>
                {article.description_full.length > 400 && (
                  <button
                    onClick={() => setDescExpanded((v) => !v)}
                    className="text-xs text-indigo mt-1"
                  >
                    {descExpanded ? "折りたたむ" : "続きを読む"}
                  </button>
                )}
              </div>
            )}

            <div className="mt-5">
              <h2 className="font-display font-bold text-sm mb-2">出品者</h2>
              <button
                onClick={() => setSelectedSellerId(article.seller_id)}
                disabled={!article.seller_id}
                className="w-full flex items-center justify-between bg-white border border-line rounded-xl px-3 py-2.5 text-sm text-indigo font-medium disabled:text-ink/30 disabled:cursor-default"
              >
                {article.seller_name || "出品者情報なし"}
                {article.seller_id && <span className="text-xs text-ink/40">詳細を見る</span>}
              </button>
            </div>

            <a
              href={article.url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-center gap-1.5 mt-5 bg-indigo text-white rounded-xl py-3 text-sm font-bold"
            >
              ジモティーで見る
              <ExternalLink size={14} />
            </a>

            <div className="mt-4 text-xs text-ink/30 text-center">
              初回確認: {formatJapaneseDateTimeFromUTC(article.first_seen_at)} ／ 最終確認:{" "}
              {formatJapaneseDateTimeFromUTC(article.last_seen_at)}
            </div>
          </div>
        )}
      </ModalShell>

      {selectedSellerId && (
        <SellerPanel
          sellerId={selectedSellerId}
          onClose={() => setSelectedSellerId(null)}
          zIndex={40}
        />
      )}
    </>
  );
}
