import { useState, useEffect, useCallback } from "react";
import { ShieldCheck, Star, Loader2, ExternalLink, RefreshCw, Ban, Eye } from "lucide-react";
import { api } from "../api/client";
import ModalShell, { ModalHeader } from "./ModalShell";
import { formatPrice } from "../utils/articleDisplay";

// 2026-08-30: 「見るまでは取らない」設計 (遅延取得)。
//   - 紹介文が省略されている出品者を初めて「続きを読む」で開いたとき、
//     まだプロフィールページを取得していなければその場で取得する
//     (以後はDBに保存済みなので再取得しない)。
//   - 「更新」ボタンは常に強制的に再取得する (評価数・投稿数等の
//     最新化)。初回に限れば「続きを読む」と全く同じ挙動になる。
function formatLastUpdated(raw) {
  if (!raw) return null;
  // sellers.profile_fetched_at は SQLite の datetime('now') 形式
  // ("YYYY-MM-DD HH:MM:SS", UTC) で入っているため、ローカル時刻表示に変換する。
  const d = new Date(raw.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("ja-JP", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function SellerPanel({ sellerId, onClose, zIndex = 30 }) {
  const [seller, setSeller] = useState(null);
  const [articles, setArticles] = useState([]);
  // seller_other_articles由来 (公式プロフィールページの全投稿一覧)。
  // 2026-09-04 新設。プロフィール未取得の出品者では空配列のまま。
  const [otherArticles, setOtherArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [descExpanded, setDescExpanded] = useState(false);
  // 「続きを読む」「更新」共通のローディング/エラー状態
  const [profileFetching, setProfileFetching] = useState(false);
  const [profileFetchError, setProfileFetchError] = useState(null);
  // NG登録／監視登録の現在状態 (seller_rules由来)。2026-09-04新設。
  // null = 未登録、{id, rule_type: "ng"|"watch"} = 登録済み。
  const [sellerRule, setSellerRule] = useState(null);
  const [ruleActionPending, setRuleActionPending] = useState(null); // "ng" | "watch" | null
  const [ruleError, setRuleError] = useState(null);

  const loadSellerRule = useCallback(() => {
    return api
      .getSellerRule(sellerId)
      .then(setSellerRule)
      .catch(() => setSellerRule(null));
  }, [sellerId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDescExpanded(false);
    setProfileFetchError(null);
    setRuleError(null);
    Promise.all([
      api.getSeller(sellerId),
      api.getSellerArticles(sellerId),
      api.getSellerOtherArticles(sellerId),
      api.getSellerRule(sellerId),
    ])
      .then(([s, a, oa, rule]) => {
        if (!cancelled) {
          setSeller(s);
          setArticles(a);
          setOtherArticles(oa);
          setSellerRule(rule);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [sellerId]);

  // NG登録／監視登録ボタン共通の処理。
  // - 現在すでにそのrule_typeで登録済みなら解除 (削除)。
  // - 未登録、または別のrule_typeで登録済みなら新規登録を試みる
  //   (別種別で登録済みの場合はDB側の一意制約によりバックエンドが
  //   409を返す。ユーザーの合意により、事前に防ぐのではなく
  //   エラーメッセージで一意制約を伝える方針)。
  const handleRuleAction = async (ruleType) => {
    setRuleError(null);
    setRuleActionPending(ruleType);
    try {
      if (sellerRule && sellerRule.rule_type === ruleType) {
        await api.deleteSellerRule(sellerRule.id);
      } else {
        await api.createSellerRule({
          seller_id: sellerId,
          seller_name: seller?.seller_name || null,
          rule_type: ruleType,
        });
      }
      await loadSellerRule();
    } catch (e) {
      setRuleError(e.message);
    } finally {
      setRuleActionPending(null);
    }
  };

  const openExternalProfile = () => {
    if (seller?.seller_profile_url) {
      window.open(seller.seller_profile_url, "_blank", "noreferrer");
    }
  };

  // プロフィールページを取得してDBを更新する共通処理。
  // 「続きを読む」「更新」の両方から呼ばれる。
  const doFetchProfile = async () => {
    setProfileFetchError(null);
    setProfileFetching(true);
    try {
      const updated = await api.fetchSellerProfile(sellerId);
      setSeller(updated);
      // 2026-09-04: プロフィール取得成功時、seller_other_articles も
      // 更新されているはずなので合わせて再取得し、「他の投稿」表示に
      // 反映する。
      const oa = await api.getSellerOtherArticles(sellerId);
      setOtherArticles(oa);
      return true;
    } catch (e) {
      setProfileFetchError(e.message);
      return false;
    } finally {
      setProfileFetching(false);
    }
  };

  // 「続きを読む」: 未取得ならプロフィールページを取得してから展開する。
  // 取得済みなら通信せず即座に展開するだけ。
  const handleReadMore = async () => {
    if (descExpanded) {
      setDescExpanded(false);
      return;
    }
    if (seller?.profile_fetched_at) {
      setDescExpanded(true);
      return;
    }
    const ok = await doFetchProfile();
    if (ok) setDescExpanded(true);
  };

  // 「更新」ボタン: profile_fetched_at の状態に関わらず必ず取得し直す。
  const handleRefresh = async () => {
    await doFetchProfile();
  };

  return (
    <ModalShell onClose={onClose} zIndex={zIndex}>
      <ModalHeader title="出品者情報" onClose={onClose} />

      {loading && (
        <div className="flex justify-center py-16 text-ink/30">
          <Loader2 size={24} className="animate-spin" />
        </div>
      )}

      {!loading && error && (
        <div className="text-alert text-sm bg-alert/10 rounded-xl mx-4 my-4 p-4 text-center">
          {error}
        </div>
      )}

      {!loading && seller && (
        <div className="px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-indigo/10 flex items-center justify-center font-display font-bold text-indigo text-lg shrink-0">
              {(seller.seller_name || "?").charAt(0)}
            </div>
            <div className="min-w-0">
              {/*
                2026-08-26: ユーザー名クリックでジモティー上の
                プロフィールURLを新規タブで開けるようにした
                (「この出品者の他の投稿」と同じ操作感に揃える)。
                seller_profile_url が無い場合はクリックできない
                (装飾なしのテキストにする)。
              */}
              {seller.seller_profile_url ? (
                <button
                  onClick={openExternalProfile}
                  className="font-bold text-indigo hover:underline flex items-center gap-1 truncate"
                  title="ジモティーでプロフィールを見る"
                >
                  <span className="truncate">{seller.seller_name || "名称不明"}</span>
                  <ExternalLink size={12} className="shrink-0" />
                </button>
              ) : (
                <p className="font-bold truncate">{seller.seller_name || "名称不明"}</p>
              )}
              <div className="flex items-center gap-1 text-xs text-ink/50">
                {seller.rating !== null && (
                  <span className="flex items-center gap-0.5">
                    <Star size={12} className="fill-clay text-clay" />
                    {seller.rating.toFixed(1)}
                    {seller.rating_count !== null && ` (${seller.rating_count})`}
                  </span>
                )}
                {seller.post_count !== null && <span>・投稿{seller.post_count}件</span>}
              </div>
            </div>
          </div>

          <div className="flex gap-2 mt-3">
            {seller.identity_verified && (
              <span className="flex items-center gap-1 text-xs bg-indigo/10 text-indigo px-2 py-1 rounded-full">
                <ShieldCheck size={12} /> 身分証確認済み
              </span>
            )}
            {seller.phone_verified && (
              <span className="flex items-center gap-1 text-xs bg-indigo/10 text-indigo px-2 py-1 rounded-full">
                <ShieldCheck size={12} /> 電話番号確認済み
              </span>
            )}
          </div>

          {/*
            2026-09-04新設: NG登録・監視登録ボタン。常時表示の横並び。
            NgButton(投稿カード上のポップオーバー方式)とは別に、出品者
            パネルではその場で状態が見えるほうが分かりやすいという判断
            で単独ボタンにしている。すでに同じ種別で登録済みならボタンは
            「解除」として働き、別種別で登録済みの状態でもう一方を押すと
            DB側の一意制約により409が返るので、そのままエラー表示する。
          */}
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => handleRuleAction("ng")}
              disabled={ruleActionPending !== null}
              className={`flex-1 flex items-center justify-center gap-1.5 text-xs font-bold py-2 rounded-xl border disabled:opacity-60 ${
                sellerRule?.rule_type === "ng"
                  ? "bg-alert text-white border-alert"
                  : "bg-white text-alert border-line"
              }`}
            >
              {ruleActionPending === "ng" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Ban size={13} />
              )}
              {sellerRule?.rule_type === "ng" ? "NG解除" : "NG登録"}
            </button>
            <button
              onClick={() => handleRuleAction("watch")}
              disabled={ruleActionPending !== null}
              className={`flex-1 flex items-center justify-center gap-1.5 text-xs font-bold py-2 rounded-xl border disabled:opacity-60 ${
                sellerRule?.rule_type === "watch"
                  ? "bg-indigo text-white border-indigo"
                  : "bg-white text-indigo border-line"
              }`}
            >
              {ruleActionPending === "watch" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Eye size={13} />
              )}
              {sellerRule?.rule_type === "watch" ? "監視解除" : "監視登録"}
            </button>
          </div>
          {ruleError && <p className="text-xs text-alert mt-1.5">{ruleError}</p>}

          {seller.description && (
            <div className="mt-3">
              <button
                onClick={handleReadMore}
                disabled={profileFetching}
                className="text-left w-full disabled:opacity-60"
                title={descExpanded ? "折りたたむ" : "全文を表示"}
              >
                <p
                  className={`text-sm text-ink/70 whitespace-pre-line leading-relaxed ${
                    descExpanded ? "" : "line-clamp-3"
                  }`}
                >
                  {seller.description}
                </p>
                <span className="text-xs text-indigo mt-0.5 inline-flex items-center gap-1">
                  {profileFetching && !descExpanded && (
                    <Loader2 size={11} className="animate-spin" />
                  )}
                  {descExpanded ? "折りたたむ" : profileFetching ? "取得中..." : "続きを読む"}
                </span>
              </button>
            </div>
          )}

          {profileFetchError && (
            <p className="text-xs text-alert mt-2">{profileFetchError}</p>
          )}

          <div className="flex items-center justify-between mt-3">
            <p className="text-xs text-ink/40">
              {seller.profile_fetched_at
                ? `プロフィール最終更新: ${formatLastUpdated(seller.profile_fetched_at)}`
                : "プロフィール詳細は未取得です"}
            </p>
            <button
              onClick={handleRefresh}
              disabled={profileFetching}
              className="flex items-center gap-1 text-xs text-indigo shrink-0 disabled:opacity-60"
              title="プロフィールページを取得し直して最新情報に更新する"
            >
              <RefreshCw size={11} className={profileFetching ? "animate-spin" : ""} />
              更新
            </button>
          </div>

          {(seller.rating_good !== null || seller.residential_area) && (
            <div className="grid grid-cols-3 gap-2 mt-4 text-center">
              {seller.rating_good !== null && (
                <div className="bg-white rounded-xl py-2 border border-line">
                  <p className="text-xs text-ink/40">良い</p>
                  <p className="font-mono font-bold">{seller.rating_good}</p>
                </div>
              )}
              {seller.rating_normal !== null && (
                <div className="bg-white rounded-xl py-2 border border-line">
                  <p className="text-xs text-ink/40">普通</p>
                  <p className="font-mono font-bold">{seller.rating_normal}</p>
                </div>
              )}
              {seller.rating_bad !== null && (
                <div className="bg-white rounded-xl py-2 border border-line">
                  <p className="text-xs text-ink/40">悪い</p>
                  <p className="font-mono font-bold">{seller.rating_bad}</p>
                </div>
              )}
            </div>
          )}

          {(() => {
            // 2026-09-04: プロフィール取得済み (otherArticlesが1件以上) なら
            // 公式プロフィールページの投稿一覧 (1ページ目分) を優先表示する。
            // 未取得の場合は、監視ツールが偶然検知した投稿 (articles) に
            // フォールバックする (従来の挙動を維持)。
            //
            // 2026-09-04 方針転換: プロフィールページは1ページ目のみ取得する
            // (次ページは辿らない、低頻度アクセスの原則を優先)。そのため
            // 合計出品数 (seller.post_count、「全◯件中」の表記由来) と
            // 実際に表示できる件数 (displayList.length、最大10件程度) が
            // 一致しないことがある。見出しでは「合計」と「表示中」を分けて
            // 示し、差がある場合はその旨を注記する。
            const usingOfficialList = otherArticles.length > 0;
            const displayList = usingOfficialList ? otherArticles : articles;
            const totalCount = usingOfficialList ? seller.post_count : null;
            const hasMore = totalCount != null && totalCount > displayList.length;
            return (
              <>
                <h3 className="font-display font-bold text-sm mt-5 mb-2">
                  この出品者の他の投稿
                  {totalCount != null ? (
                    <span className="font-normal text-ink/50">
                      （全{totalCount}件中 {displayList.length}件を表示）
                    </span>
                  ) : (
                    <span className="font-normal text-ink/50">（{displayList.length}件）</span>
                  )}
                </h3>
                <div className="flex flex-col gap-2">
                  {displayList.map((a) => (
                    <a
                      key={a.article_id}
                      href={a.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-between bg-white rounded-xl px-3 py-2 border border-line text-sm"
                    >
                      <span className="truncate flex-1">
                        {usingOfficialList ? a.title : a.full_title || a.list_title}
                      </span>
                      <span className="font-mono text-clay font-bold ml-2 shrink-0">
                        {formatPrice(a.price)}
                      </span>
                    </a>
                  ))}
                </div>
                {hasMore && (
                  <p className="text-xs text-ink/40 mt-2">
                    ※ 残り{totalCount - displayList.length}件は表示していません。全件確認するには公式サイトをご覧ください。
                  </p>
                )}
                {!usingOfficialList && !seller.profile_fetched_at && (
                  <p className="text-xs text-ink/40 mt-2">
                    ※「続きを読む」または「更新」を押すと、公式プロフィール
                    ページの投稿一覧（1ページ目）を取得して表示します
                  </p>
                )}
              </>
            );
          })()}
        </div>
      )}
    </ModalShell>
  );
}
