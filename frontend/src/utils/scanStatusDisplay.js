/*
 * 2026-09-10新設。
 * scan_state.last_scanned_at / next_scan_estimated_at (いずれも
 * SQLiteのdatetime('now')形式="YYYY-MM-DD HH:MM:SS"、UTC) を、
 * 「5分前」「まもなく」「1時間30分後」のような分かりやすい相対時間
 * 表示に変換する。ヘッダーの旧・手動更新ボタン跡地
 * (前回更新/次回更新の表示) で使う。
 */

// SQLiteのdatetime('now')はUTCのタイムゾーン情報無し文字列
// ("2026-09-10 07:00:00") で返ってくるため、明示的にUTCとして
// パースする (末尾にZを付けてDateに解釈させる)。
function parseUtcTimestamp(value) {
  if (!value) return null;
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  const withZone = iso.endsWith("Z") ? iso : `${iso}Z`;
  const date = new Date(withZone);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatMinutes(totalMinutes) {
  const minutes = Math.round(totalMinutes);
  if (minutes < 1) return "1分未満";
  if (minutes < 60) return `${minutes}分`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours}時間` : `${hours}時間${rest}分`;
}

/**
 * 「5分前に更新」のような文字列を返す。timestampがnullなら
 * 「まだ更新していません」を返す。
 */
export function formatLastScannedLabel(lastScannedAt, now = new Date()) {
  const date = parseUtcTimestamp(lastScannedAt);
  if (date === null) return "まだ更新していません";

  const diffMs = now.getTime() - date.getTime();
  if (diffMs < 60000) return "たった今更新";
  return `${formatMinutes(diffMs / 60000)}前に更新`;
}

/**
 * 「次回: 30分後」のような文字列を返す。timestampがnull
 * (=自動更新が未設定) ならnullを返す (呼び出し元は非表示にする)。
 * 既に予定時刻を過ぎている場合は「まもなく次回更新」を返す
 * (自動更新ループのポーリング間隔分のタイムラグを考慮)。
 */
export function formatNextScanLabel(nextScanEstimatedAt, now = new Date()) {
  const date = parseUtcTimestamp(nextScanEstimatedAt);
  if (date === null) return null;

  const diffMs = date.getTime() - now.getTime();
  if (diffMs <= 0) return "まもなく次回更新";
  return `次回: ${formatMinutes(diffMs / 60000)}後`;
}
