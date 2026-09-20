/*
 * 2026-09-10新設。
 * 「n回目の値変更」ラベル (カード/リスト/表モード共通)。
 *
 * - price_change_countが0 (一度も値変更が確認されていない) なら
 *   何も表示しない。
 * - 値上げ/値下げの方向性 (UP/DOWN) は持たない。回数のみ表示する
 *   (ユーザーとの合意事項)。
 * - 直近の巡回で変化したかに関わらず、監視を始めてからの累計回数を
 *   常に表示し続ける (title_changed_atのような「直近のみ」表示とは
 *   異なる仕様)。
 *
 * 2026-09-11追加: compact指定で「n回」だけの極小表示にする。
 * 表モードは列幅が固定 (utils/articleListConfig.js) で、価格列の
 * 横幅が狭いため、通常表示 (「n回目の値変更」) だと列からはみ出して
 * 隣の列のテキストと重なってしまう不具合があった。表モードでは
 * この省スペース版を使う。
 */
export default function PriceChangeBadge({ count, className = "", compact = false }) {
  if (!count) return null;

  return (
    <span
      className={`inline-flex items-center shrink-0 text-[10px] font-bold text-clay bg-clay/10 border border-clay/20 rounded-full whitespace-nowrap ${
        compact ? "px-1 py-0.5" : "px-1.5 py-0.5"
      } ${className}`}
      title={`このツールで監視を始めてから${count}回、価格の変更を確認しています`}
    >
      {compact ? `${count}回` : `${count}回目の値変更`}
    </span>
  );
}
