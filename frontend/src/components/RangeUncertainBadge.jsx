/*
 * 2026-09-11新設。「終了」タブ再設計。
 *
 * missing_kind='range_uncertain' の投稿にだけ表示するラベル。
 * 取得範囲 (ページ数/日数設定) の外に押し出されただけの可能性が
 * あり、本当に終了したかどうかまだ確認していないことを示す
 * (confirmed_closedは自動で個別ページ確認済みのため、このラベルは
 * 出さない = 表示が無ければ「終了確定」という扱い)。
 * PriceChangeBadgeと似た見た目にする (ユーザーとの合意事項)。
 */
export default function RangeUncertainBadge({ missingKind, className = "" }) {
  if (missingKind !== "range_uncertain") return null;

  return (
    <span
      className={`inline-flex items-center shrink-0 text-[10px] font-bold text-ink/60 bg-white/90 border border-line rounded-full px-1.5 py-0.5 whitespace-nowrap ${className}`}
      title="取得範囲の外に押し出されただけで、まだ本当に終了したかは確認できていません"
    >
      監視範囲外
    </span>
  );
}
