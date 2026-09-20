import { Loader2 } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import ArticleCard from "../components/ArticleCard";
import ArticleRow from "../components/ArticleRow";
import ArticleTable from "../components/ArticleTable";
import SellerPanel from "../components/SellerPanel";
import ArticleDetailModal from "../components/ArticleDetailModal";
import Pagination from "../components/Pagination";
import ArticleListHeader from "../components/ArticleListHeader";
import { useArticleListState } from "../hooks/useArticleListState";

// 2026-08-26: 当初はテーブルモードのみ画面幅いっぱい(max-w-full)、
// カード/リストはmax-w-mdという別々の横幅認識だったが、
// 「PCで見ると横幅が狭いのが気になる」というフィードバックを受けて
// 3モード共通でmax-w-fullに統一した。カード/リストの見た目自体は
// 内部のグリッド/リストの最大幅で別途調整する。
export default function ArticleListPage() {
  const navigate = useNavigate();
  const { articleId } = useParams();
  const state = useArticleListState();
  const {
    isMissingTab,
    loading,
    loadError,
    filteredArticles,
    hasActiveFilters,
    viewMode,
    cardColumns,
    pagedArticles,
    setSelectedSellerId,
    handleWatchChange,
    handleArticleConfirmed,
    thumbnailSize,
    visibleColumns,
    columnWidths,
    setColumnWidths,
    currentPage,
    totalPages,
    setCurrentPage,
    scrollToTop,
    selectedSellerId,
  } = state;

  const openArticle = (article) => {
    navigate(`/articles/${article.article_id}`);
  };

  return (
    <div className="max-w-full px-2 sm:px-6 mx-auto pb-24">
      <ArticleListHeader state={state} />

      <main className="pt-4">

        {loading && (
          <div className="flex justify-center py-16 text-ink/30">
            <Loader2 size={24} className="animate-spin" />
          </div>
        )}

        {loadError && (
          <div className="text-alert text-sm bg-alert/10 rounded-xl p-4 text-center">
            {loadError}
            <p className="text-xs text-ink/50 mt-1">
              バックエンド(uvicorn)が起動しているか確認してください。
            </p>
          </div>
        )}

        {!loading && !loadError && filteredArticles.length === 0 && (
          <div className="text-center py-16 text-ink/40 text-sm">
            {isMissingTab
              ? "公開終了の投稿はありません。"
              : hasActiveFilters
              ? "条件に一致する投稿がありません。"
              : "該当する投稿がありません。"}
          </div>
        )}

        {/*
          2026-09-11変更: 「終了」タブ再設計により、専用の
          ClosedArticleCard縦一列レイアウトを廃止し、他タブと同じ
          card/list/tableの3表示モードに統一した (ユーザーとの合意
          事項)。各コンポーネントにはisMissingTab/onConfirmedを渡し、
          「終了」タブのときだけ「監視範囲外」ラベル・再確認ボタンを
          表示する。
        */}
        {!loading && !loadError && filteredArticles.length > 0 && viewMode === "card" && (
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: `repeat(${cardColumns}, minmax(0, 1fr))` }}
          >
            {pagedArticles.map((a) => (
              <ArticleCard
                key={a.article_id}
                article={a}
                onOpenSeller={setSelectedSellerId}
                onWatchChange={handleWatchChange}
                onOpenArticle={openArticle}
                isMissingTab={isMissingTab}
                onConfirmed={handleArticleConfirmed}
              />
            ))}
          </div>
        )}

        {!loading && !loadError && filteredArticles.length > 0 && viewMode === "list" && (
          <div className="rounded-xl overflow-hidden border border-line">
            {pagedArticles.map((a) => (
              <ArticleRow
                key={a.article_id}
                article={a}
                onOpenSeller={setSelectedSellerId}
                onOpenArticle={openArticle}
                onWatchChange={handleWatchChange}
                thumbnailSize={thumbnailSize}
                isMissingTab={isMissingTab}
                onConfirmed={handleArticleConfirmed}
              />
            ))}
          </div>
        )}

        {!loading && !loadError && filteredArticles.length > 0 && viewMode === "table" && (
          <ArticleTable
            articles={pagedArticles}
            onOpenSeller={setSelectedSellerId}
            onOpenArticle={openArticle}
            onWatchChange={handleWatchChange}
            thumbnailSize={thumbnailSize}
            visibleColumns={visibleColumns}
            columnWidths={columnWidths}
            onColumnWidthsChange={setColumnWidths}
            isMissingTab={isMissingTab}
            onConfirmed={handleArticleConfirmed}
          />
        )}

        {!loading && !loadError && filteredArticles.length > 0 && (
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            onChange={(page) => {
              setCurrentPage(page);
              scrollToTop();
            }}
          />
        )}
      </main>

      {selectedSellerId && (
        <SellerPanel
          sellerId={selectedSellerId}
          onClose={() => setSelectedSellerId(null)}
        />
      )}

      {articleId && (
        <ArticleDetailModal
          articleId={articleId}
          onClose={() => navigate("/")}
        />
      )}
    </div>
  );
}
