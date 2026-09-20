import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

/*
 * 2026-09-10新設。
 *
 * 背景: これまで「巡回中かどうか」「今すぐ更新」ボタンはArticleListPage
 * 内のローカルstate (scanning) で管理されていた。このため、
 *   - 一覧画面から設定画面に移ると、更新中であることを示すUIが
 *     消えてしまう (実際の巡回自体はサーバー側で継続しているが、
 *     見た目上は中断したように見える)
 *   - 自動更新 (サーバー側定期実行) が今まさに動いていても、
 *     ブラウザ側は一切それを検知できない
 * という問題があった。
 *
 * この Context は、GET /api/scan-status をポーリングしてサーバー側の
 * 実行状態をアプリ全体 (BottomNav・ヘッダー・設定画面のどこからでも)
 * から参照できるようにする。ページ遷移やブラウザのリロードを挟んでも、
 * この関数はサーバー側の実行状態をそのまま反映するだけなので状態が
 * 失われない。
 *
 * 2026-09-15追加: トースト通知・ブラウザ通知 (Web Notifications API)。
 *
 * GET /api/scan-status のレスポンスには、直近の巡回で「検索」タブの
 * 条件にヒットした新規投稿一覧 (notified_articles) と、それがいつの
 * 巡回結果か (notified_at) が含まれる (バックエンド側の詳細は
 * api/routers/scan.py・scheduler/scan_runner.py参照)。
 *
 * このContextは、ポーリングのたびにnotified_atが「前回ポーリング時
 * から変化したか」を見て、変化していれば「新しい巡回結果」と判断し、
 * 通知設定 (Discord/アプリ内/ブラウザ) のうちアプリ内トースト・
 * ブラウザ通知が有効な場合に、それぞれの通知UIを発火する。
 * notified_atが変化していなければ (＝前回と同じ巡回結果のまま)、
 * 何度ポーリングしても再通知はしない (同じ内容を毎回のポーリングで
 * 重複通知しないようにするため)。
 *
 * 通知設定自体 (in_app_enabled / browser_enabled) はGET
 * /api/settings/discord-notification から取得する。設定画面
 * (DiscordNotificationSettings.jsx) で保存された値を、ポーリングの
 * たびに (状態の変化を見逃さないよう) 併せて取得する。
 */

const ScanStatusContext = createContext(null);

// 2026-09-10: ポーリング間隔。ユーザーとの打ち合わせで「20秒くらい」
// と合意した値 (体感の良さとリクエスト数のバランス)。
const POLL_INTERVAL_MS = 20000;

// 2026-09-15追加: アプリ内トーストの自動消滅までの時間 (ミリ秒)。
// 手動で閉じることもできるが、放置しても画面が埋まり続けないように
// 一定時間後に自動で消す。
const TOAST_AUTO_DISMISS_MS = 8000;

let toastIdCounter = 0;

export function ScanStatusProvider({ children }) {
  const [status, setStatus] = useState({
    isScanning: false,
    lastScannedAt: null,
    autoScanIntervalMinutes: null,
    nextScanEstimatedAt: null,
    // 2026-09-10追加: 巡回中の進捗 (BottomNav直下の表示用)。
    // 巡回中でなければ全てnull。progressMaxPageは取得範囲が
    // 'pages'モードのときのみ値を持つ ('days'モードは事前に何ページで
    // 終わるか分からないため常にnull。UI側は上限不明のバー表示にする)。
    progressCurrentPage: null,
    progressMaxPage: null,
    progressSeenCount: null,
  });
  // 手動更新ボタンを押してからサーバーの応答が返るまでの間、
  // ポーリングの反映を待たずに即座に「更新中」のUIへ切り替えるための
  // 楽観的フラグ (ボタン連打防止も兼ねる)。
  const [manualTriggering, setManualTriggering] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [scanError, setScanError] = useState(null);
  const pollTimerRef = useRef(null);

  // 2026-09-15追加: アプリ内トーストの表示中リスト。
  const [toasts, setToasts] = useState([]);
  // 直前にポーリングで見た notified_at。変化を検知するための参照値
  // (レンダーを起こす必要が無いのでuseStateではなくuseRefで持つ)。
  const lastSeenNotifiedAtRef = useRef(null);
  // 通知設定 (アプリ内トースト・ブラウザ通知の有効/無効)。設定画面と
  // 同じAPIをポーリングのたびに読み直すことで、設定変更後すぐに
  // (最大でも次のポーリング間隔以内に) 反映されるようにする。
  const notificationSettingsRef = useRef({ inAppEnabled: false, browserEnabled: false });
  // 2026-09-15追加: アプリ起動直後の最初のポーリングでは、サーバー側
  // に既にnotified_atが入っていても「新着」として通知しない
  // (アプリを開いた瞬間に過去の巡回結果がどっと通知されるのを防ぐ)。
  const isFirstStatusLoadRef = useRef(true);

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (article) => {
      const id = ++toastIdCounter;
      setToasts((prev) => [...prev, { id, article }]);
      setTimeout(() => dismissToast(id), TOAST_AUTO_DISMISS_MS);
    },
    [dismissToast]
  );

  // 2026-09-15追加: ブラウザ通知 (Web Notifications API) を発火する。
  // タブを開いている間のみ動作する設計 (Service Worker等による
  // バックグラウンド配信は行わない、ユーザーとの合意事項)。許可が
  // 下りていない場合は何もしない (設定画面側で許可をリクエストする
  // フローを用意しているため、ここで改めてrequestPermission()は
  // 呼ばない。ユーザーの操作を伴わない自動的な許可ダイアログの表示は
  // ブラウザによってはブロックされる)。
  const fireBrowserNotification = useCallback((article) => {
    if (typeof Notification === "undefined") return;
    if (Notification.permission !== "granted") return;
    try {
      const priceText = article.price != null ? `${article.price.toLocaleString()}円` : "価格不明";
      const notification = new Notification("ジモティー新着", {
        body: `${article.list_title}（${priceText}）`,
        // 2026-09-15: thumbnail_urlが無い投稿もあるため、iconはundefined
        // (ブラウザ標準のデフォルトアイコン) にフォールバックする。
        icon: article.thumbnail_url || undefined,
        tag: `jimoty-article-${article.article_id}`,
      });
      notification.onclick = () => {
        window.focus();
        window.open(article.url, "_blank", "noopener,noreferrer");
        notification.close();
      };
    } catch {
      // 2026-09-15: 一部のブラウザ (通知権限はgrantedだがOS側で
      // ブロックされている等) でNotification生成自体が例外を投げる
      // ことがあるが、アプリの他機能に影響させないよう握りつぶす。
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const [data, notificationSettings] = await Promise.all([
        api.getScanStatus(),
        api.getDiscordNotificationSettings().catch(() => null),
      ]);

      setStatus({
        isScanning: data.is_scanning,
        lastScannedAt: data.last_scanned_at,
        autoScanIntervalMinutes: data.auto_scan_interval_minutes,
        nextScanEstimatedAt: data.next_scan_estimated_at,
        progressCurrentPage: data.progress_current_page,
        progressMaxPage: data.progress_max_page,
        progressSeenCount: data.progress_seen_count,
      });

      if (notificationSettings) {
        notificationSettingsRef.current = {
          inAppEnabled: notificationSettings.in_app_enabled || false,
          browserEnabled: notificationSettings.browser_enabled || false,
        };
      }

      // 2026-09-15追加: 通知対象の差分検知。notified_atが前回の
      // ポーリング時から変化していれば「新しい巡回結果」とみなす。
      // 初回ロード時 (isFirstStatusLoadRef.current === true) は、
      // 過去の巡回結果を「新着」として通知しないよう、参照値の更新
      // のみ行って実際の通知はスキップする。
      const notifiedAtChanged =
        data.notified_at !== null && data.notified_at !== lastSeenNotifiedAtRef.current;
      const shouldNotify = notifiedAtChanged && !isFirstStatusLoadRef.current;

      if (data.notified_at !== null) {
        lastSeenNotifiedAtRef.current = data.notified_at;
      }
      isFirstStatusLoadRef.current = false;

      if (shouldNotify && Array.isArray(data.notified_articles) && data.notified_articles.length > 0) {
        const { inAppEnabled, browserEnabled } = notificationSettingsRef.current;
        for (const article of data.notified_articles) {
          if (inAppEnabled) pushToast(article);
          if (browserEnabled) fireBrowserNotification(article);
        }
      }
    } catch {
      // 2026-09-10: ポーリングの1回の失敗でUIを壊さない
      // (次回のポーリングでまた取得を試みる)。
    }
  }, [pushToast, fireBrowserNotification]);

  useEffect(() => {
    refreshStatus();
    pollTimerRef.current = setInterval(refreshStatus, POLL_INTERVAL_MS);
    return () => clearInterval(pollTimerRef.current);
  }, [refreshStatus]);

  // 一覧画面の「今すぐ更新」ボタンから呼ばれる。手動更新も自動更新も
  // 同じサーバー側の実行状態を共有するため、ここでトリガーした後は
  // refreshStatus()で最新状態を取り直すだけでよい。
  const triggerManualScan = useCallback(async () => {
    setManualTriggering(true);
    setScanResult(null);
    setScanError(null);
    try {
      const result = await api.triggerScan();
      setScanResult(result);
      await refreshStatus();
      return result;
    } catch (e) {
      // 2026-09-10: 既に巡回中 (自動更新中など) だった場合、
      // バックエンドは409を返す。この場合はエラー表示せず、
      // 単に「今まさに動いている巡回」の状態をポーリングに
      // 委ねる (ユーザーから見れば更新自体は行われている)。
      if (!String(e.message).includes("409")) {
        setScanError(
          "巡回に失敗しました。ネットワーク接続を確認するか、しばらく経ってから再度お試しください。"
        );
      }
      await refreshStatus();
      throw e;
    } finally {
      setManualTriggering(false);
    }
  }, [refreshStatus]);

  const cancelScan = useCallback(async () => {
    try {
      const result = await api.cancelScan();
      if (result.cancelled) {
        // 2026-09-10: 停止「要求」が伝わったことの簡易フィードバック。
        // 実際に巡回が止まるのはページ境界のタイミング (数秒程度)
        // 遅れるため、確定メッセージではなく経過を伝える文言にする。
        // 自動更新側の巡回結果 (ScanResult) はブラウザに返る仕組みが
        // 無いため、手動更新時のような詳細な結果表示はできない。
        setScanResult(null);
        setScanError(null);
      }
    } finally {
      await refreshStatus();
    }
  }, [refreshStatus]);

  const value = {
    ...status,
    // 手動トリガー直後のタイムラグ (サーバーが実行中フラグを立てる前)
    // もアイコン回転に反映されるよう、isScanningはこの2つのORで
    // 判定する。
    isScanning: status.isScanning || manualTriggering,
    scanResult,
    scanError,
    setScanError,
    triggerManualScan,
    cancelScan,
    refreshStatus,
    // 2026-09-15追加: トースト通知の表示状態と操作。
    toasts,
    dismissToast,
  };

  return <ScanStatusContext.Provider value={value}>{children}</ScanStatusContext.Provider>;
}

export function useScanStatus() {
  const ctx = useContext(ScanStatusContext);
  if (!ctx) {
    throw new Error("useScanStatus() は ScanStatusProvider の内側で使ってください");
  }
  return ctx;
}
