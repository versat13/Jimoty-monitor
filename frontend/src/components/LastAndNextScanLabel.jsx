import { useState, useEffect } from "react";
import { useScanStatus } from "../context/ScanStatusContext";
import { formatLastScannedLabel, formatNextScanLabel } from "../utils/scanStatusDisplay";

/*
 * 2026-09-10新設。
 * ヘッダーの旧・手動更新ボタン跡地に置く「前回いつ更新したか／次回は
 * いつ頃か」の表示。手動・自動どちらの更新でも同じ
 * scan_state.last_scanned_at を参照するため区別しない
 * (ユーザーとの合意事項)。自動更新が未設定の場合は次回表示を省略する。
 * 表示中に時間が経過しても古い表示のままにならないよう、1分ごとに
 * 現在時刻を再計算する。
 */
export default function LastAndNextScanLabel() {
  const { lastScannedAt, nextScanEstimatedAt } = useScanStatus();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(timer);
  }, []);

  const lastLabel = formatLastScannedLabel(lastScannedAt, now);
  const nextLabel = formatNextScanLabel(nextScanEstimatedAt, now);

  return (
    <div className="flex flex-col items-end leading-tight text-ink/50 text-[11px]">
      <span>{lastLabel}</span>
      {nextLabel && <span>{nextLabel}</span>}
    </div>
  );
}
