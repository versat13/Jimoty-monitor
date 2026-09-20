import { useState, useEffect, useRef } from "react";
import { NavLink } from "react-router-dom";
import { List, SlidersHorizontal, RefreshCw, Loader2, Square } from "lucide-react";
import { useScanStatus } from "../context/ScanStatusContext";

const TABS = [
  { to: "/", label: "一覧", icon: List, end: true },
  { to: "/settings", label: "設定", icon: SlidersHorizontal, end: false },
];

// 2026-09-14新設: 2段階タップの猶予時間。この間にもう一度タップ
// しなければ、armed状態は自動的に解除される (誤タップの影響を
// 最小限にするため)。
const ARM_TIMEOUT_MS = 3000;

/*
 * 2026-09-10変更: 手動更新ボタンをヘッダー(ArticleListPage内)から
 * BottomNavの左側へ移動した。
 *
 * 理由 (ユーザーとの打ち合わせ):
 *   - 手動更新中に一覧から設定に移ると、以前はUI上「更新が中断された」
 *     ように見えていた (実際にはローカルstateが失われていただけ)。
 *   - 自動更新 (サーバー側定期実行) が動いていても、それを示す
 *     視覚的な目安が一切無かった。
 * BottomNavはどのページでも常に表示されているため、ここに置くことで
 * 手動・自動を問わず、画面のどこにいても更新中であることが
 * 常時分かるようにした (ScanStatusContext経由でサーバー側の実行状態を
 * ポーリングして反映するため、ページ遷移やリロードでも状態が保たれる)。
 *
 * 2026-09-14変更 (2段階タップ、ユーザーとの合意事項):
 *   設定タブなど他のBottomNavボタンと見た目が似ているため、トップ
 *   ページに戻るつもりで誤ってタップしてしまう、という指摘を受けた。
 *   これに対応するため、更新開始前に「1回目のタップでボタンが
 *   確認待ち(armed)状態に変化し、3秒以内に2回目タップすると実際に
 *   実行される」という2段階の確認を挟むようにした。何もしなければ
 *   3秒後に自動でarmed状態が解除され、誤タップの影響が残らない
 *   ようにしている。
 *
 * 2026-09-15変更 (停止側も2段階タップに統一、ユーザーとの合意事項):
 *   更新開始は上記の2段階タップ(armed、indigo色)でアニメーション
 *   付きの確認になっている一方、更新停止だけはconfirm()という
 *   ブラウザ標準の警告ダイアログが割り込む形になっており、
 *   「開始と停止で確認の見た目・操作感が統一されていない」という
 *   指摘を受けた。これに対応するため、停止側も同じ「1回目のタップで
 *   ボタンが確認待ち状態に変化し、3秒以内に2回目タップすると実際に
 *   実行される」という2段階タップ方式に統一した。
 *   開始側のarmed(indigo色)とは別のstopArmed状態として管理し、
 *   停止確認中であることが一目で分かるよう警告色(alert)で表示する
 *   (「これから停止するという注意喚起」の意味合いを保ちつつ、
 *   confirm()のようなブラウザ標準ダイアログでの割り込みは行わない)。
 *   confirm()は使わなくなったため撤去した。
 *
 * タップ時の挙動:
 *   - 更新中でない・armed状態でない場合: armed状態にする (1回目)。
 *   - 更新中でない・armed状態の場合: 手動更新を開始する (2回目)。
 *   - 更新中・stopArmed状態でない場合: stopArmed状態にする (1回目)。
 *   - 更新中・stopArmed状態の場合: 緊急停止を実行する (2回目)。
 */
function ManualScanButton() {
  const { isScanning, triggerManualScan, cancelScan } = useScanStatus();
  const [armed, setArmed] = useState(false);
  const [stopArmed, setStopArmed] = useState(false);
  const armTimerRef = useRef(null);
  const stopArmTimerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (armTimerRef.current) clearTimeout(armTimerRef.current);
      if (stopArmTimerRef.current) clearTimeout(stopArmTimerRef.current);
    };
  }, []);

  // 更新が始まったら (他の画面から自動更新が走った場合等も含め)、
  // armed状態は意味を持たなくなるのでリセットしておく。
  useEffect(() => {
    if (isScanning) {
      setArmed(false);
      if (armTimerRef.current) clearTimeout(armTimerRef.current);
    } else {
      // 2026-09-15追加: 更新が終わった (停止・完了問わず) ら、
      // stopArmed状態も意味を持たなくなるのでリセットする。
      setStopArmed(false);
      if (stopArmTimerRef.current) clearTimeout(stopArmTimerRef.current);
    }
  }, [isScanning]);

  const handleClick = () => {
    if (isScanning) {
      if (!stopArmed) {
        // 1回目のタップ: stopArmed状態にし、一定時間後に自動解除する
        // タイマーをセットする (開始側のarmedと対称的な挙動)。
        setStopArmed(true);
        stopArmTimerRef.current = setTimeout(() => setStopArmed(false), ARM_TIMEOUT_MS);
        return;
      }

      // 2回目のタップ: 実際に緊急停止を実行する。
      // cancelScan() 自体はScanStatusContext側でtry/finallyにより
      // 失敗時も必ずrefreshStatus()を呼ぶ設計だが、呼び出し元の
      // ここでも念のためcatchしておく (未処理のPromise拒否を防ぐ、
      // triggerManualScan()側の書き方に揃える)。
      if (stopArmTimerRef.current) clearTimeout(stopArmTimerRef.current);
      setStopArmed(false);
      cancelScan().catch(() => {});
      return;
    }

    if (!armed) {
      // 1回目のタップ: armed状態にし、一定時間後に自動解除する
      // タイマーをセットする。
      setArmed(true);
      armTimerRef.current = setTimeout(() => setArmed(false), ARM_TIMEOUT_MS);
      return;
    }

    // 2回目のタップ: 実際に更新を開始する。
    if (armTimerRef.current) clearTimeout(armTimerRef.current);
    setArmed(false);
    // 2026-09-10: 409 (既に他の巡回が実行中) はUIに何も表示せず
    // 無視してよい (ScanStatusContext側でポーリングにより状態は
    // 自然に「更新中」表示へ揃うため)。
    triggerManualScan().catch(() => {});
  };

  const label = isScanning
    ? stopArmed
      ? "もう一度タップして停止"
      : "更新中"
    : armed
      ? "もう一度タップして更新"
      : "今すぐ更新";

  return (
    <button
      onClick={handleClick}
      aria-label={label}
      title={label}
      className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 text-xs font-bold transition-colors active:scale-95 ${
        stopArmed ? "text-white bg-alert" : armed ? "text-white bg-indigo" : "text-ink/40 font-medium"
      }`}
    >
      {isScanning ? (
        stopArmed ? (
          // 2026-09-15追加: 停止確認中(1回目タップ後)は、回転する
          // Loader2のままだと「まだ更新中なだけ」に見えて色の変化に
          // 気づきにくいため、静止した■(Square)アイコンに切り替える。
          // 開始側armedが回転していないRefreshCwのままなのと対称的な
          // 見せ方にしている。
          <Square size={18} strokeWidth={2.2} fill="currentColor" />
        ) : (
          <Loader2 size={20} strokeWidth={2.2} className="animate-spin text-indigo" />
        )
      ) : (
        <RefreshCw size={20} strokeWidth={2.2} />
      )}
      {isScanning ? (stopArmed ? "タップで停止" : "更新中") : armed ? "タップで更新" : "更新"}
    </button>
  );
}

/*
 * 2026-09-10新設。更新中の進捗表示 (BottomNavのボタン直下、常に
 * 見える帯)。
 *   - progressMaxPageがある ('pages'モード): 「2/3ページ・128件確認」
 *     ＋ 何%まで進んだかの進捗バー。
 *   - progressMaxPageが無い ('days'モード、または巡回開始直後で
 *     まだ1ページ目のcommit前): 「更新中…128件確認」＋ 上限不明の
 *     不定形アニメーションバー。
 * 巡回中でなければ何も表示しない (高さ0)。
 */
function ScanProgressBar() {
  const { isScanning, progressCurrentPage, progressMaxPage, progressSeenCount } = useScanStatus();

  if (!isScanning) return null;

  const hasPageInfo = progressCurrentPage !== null && progressCurrentPage > 0;
  const seenCount = progressSeenCount ?? 0;

  let label;
  if (hasPageInfo && progressMaxPage) {
    label = `更新中… ${progressCurrentPage}/${progressMaxPage}ページ・${seenCount}件確認`;
  } else if (hasPageInfo) {
    // 'days'モード: 上限ページが無いため件数のみ表示
    label = `更新中… ${seenCount}件確認`;
  } else {
    // 巡回開始直後、まだ1ページ目のcommit前 (進捗がサーバーにまだ
    // 反映されていないタイミング)。ポーリング間隔の都合で実際には
    // ほとんど見えないはずだが、念のためフォールバック表示を出す。
    label = "更新中…";
  }

  const progressPercent =
    hasPageInfo && progressMaxPage ? Math.min(100, Math.round((progressCurrentPage / progressMaxPage) * 100)) : null;

  return (
    <div className="px-3 pt-1.5 pb-1">
      <p className="text-[10px] text-ink/40 text-center mb-1">{label}</p>
      <div className="h-1 bg-line rounded-full overflow-hidden">
        {progressPercent !== null ? (
          <div
            className="h-full bg-indigo rounded-full transition-all duration-500"
            style={{ width: `${progressPercent}%` }}
          />
        ) : (
          // 上限不明 ('days'モード等): 左右に走る不定形アニメーション
          <div className="h-full w-1/3 bg-indigo rounded-full animate-scan-progress-indeterminate" />
        )}
      </div>
    </div>
  );
}

export default function BottomNav() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-white border-t border-line z-20">
      <ScanProgressBar />
      <div className="max-w-md mx-auto flex">
        <ManualScanButton />
        {TABS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex-1 flex flex-col items-center gap-0.5 py-2.5 text-xs font-medium transition-colors ${
                isActive ? "text-indigo" : "text-ink/40"
              }`
            }
          >
            <Icon size={20} strokeWidth={2.2} />
            {label}
          </NavLink>
        ))}
      </div>
      {/* iOS のホームインジケーター分の余白 */}
      <div className="h-safe-bottom" style={{ height: "env(safe-area-inset-bottom, 0px)" }} />
    </nav>
  );
}
