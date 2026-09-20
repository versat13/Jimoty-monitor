import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * 一覧のページネーション (2026-09-08新設)。
 *
 * 表示するページ番号は現在ページの前後2つまでに絞り、それ以外は
 * 「…」で省略する (ページ数が多くなっても横幅が破綻しないように)。
 */
export default function Pagination({ currentPage, totalPages, onChange }) {
  if (totalPages <= 1) return null;

  const pageNumbers = getVisiblePageNumbers(currentPage, totalPages);

  return (
    <div className="flex items-center justify-center gap-1 py-6">
      <button
        onClick={() => onChange(Math.max(1, currentPage - 1))}
        disabled={currentPage === 1}
        className="p-1.5 rounded-lg text-ink/50 disabled:opacity-30 hover:bg-paper/60"
        aria-label="前のページ"
      >
        <ChevronLeft size={16} />
      </button>

      {pageNumbers.map((p, i) =>
        p === "…" ? (
          <span key={`ellipsis-${i}`} className="px-1.5 text-ink/30 text-xs">
            …
          </span>
        ) : (
          <button
            key={p}
            onClick={() => onChange(p)}
            className={`min-w-[28px] h-7 px-1.5 rounded-lg text-xs font-bold transition-colors ${
              p === currentPage
                ? "bg-indigo text-white"
                : "text-ink/60 hover:bg-paper/60"
            }`}
          >
            {p}
          </button>
        )
      )}

      <button
        onClick={() => onChange(Math.min(totalPages, currentPage + 1))}
        disabled={currentPage === totalPages}
        className="p-1.5 rounded-lg text-ink/50 disabled:opacity-30 hover:bg-paper/60"
        aria-label="次のページ"
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}

function getVisiblePageNumbers(current, total) {
  const delta = 2;
  const pages = [];
  for (let i = 1; i <= total; i++) {
    if (i === 1 || i === total || (i >= current - delta && i <= current + delta)) {
      pages.push(i);
    }
  }

  const withEllipsis = [];
  let prev = null;
  for (const p of pages) {
    if (prev !== null && p - prev > 1) {
      withEllipsis.push("…");
    }
    withEllipsis.push(p);
    prev = p;
  }
  return withEllipsis;
}
