import { useState, useEffect, useCallback } from "react";
import { Send, AlertTriangle, Bell, BellOff } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

/**
 * 通知設定画面 (2026-09-13新設、2026-09-15拡張)。
 *
 * 「検索」タブ (pickup_search) の条件にヒットした新規投稿が見つかった
 * ときに、Discord Webhook・アプリ内トースト・ブラウザ通知 (Web
 * Notifications API) の3種類の通知先へ通知する機能の設定UI。
 * 検索タブの条件自体はこの画面ではなく「検索」タブ側で設定する
 * (このタブは各通知先の有効化・宛先設定のみを担当する)。
 *
 * 2026-09-15変更 (ユーザーとの合意事項):
 *   従来はDiscord Webhook専用の設定画面だったが、「Discordと共通の
 *   通知条件でアプリ内トースト通知・ブラウザ通知も追加したい」という
 *   要望を受け、この「設定＞巡回設定＞通知」タブに3種類の通知先を
 *   まとめ、それぞれ個別にON/OFF保存できるようにした。
 *   トースト通知・ブラウザ通知の実際の発火処理 (対象投稿の検知・
 *   表示・Notification APIの呼び出し) はこの画面ではなく
 *   ScanStatusContext.jsx が担う。この画面は「有効/無効の設定」を
 *   保存するだけで、実際に何か通知を表示するわけではない。
 */
export default function DiscordNotificationSettings() {
  const [webhookUrl, setWebhookUrl] = useState("");
  const [enabled, setEnabled] = useState(false);
  // 2026-09-15新設: アプリ内トースト通知・ブラウザ通知のトグル。
  const [inAppEnabled, setInAppEnabled] = useState(false);
  const [browserEnabled, setBrowserEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);
  const [testSending, setTestSending] = useState(false);
  const [testResult, setTestResult] = useState(null);
  // 2026-09-15新設: ブラウザの通知許可状態 ("default" | "granted" |
  // "denied")。Web Notifications API非対応ブラウザではnullのまま。
  // ブラウザ通知を有効化するには、OS/ブラウザ側の許可 (Notification.
  // requestPermission()) が別途必要なため、このコンポーネントの
  // browserEnabled (アプリ側の設定) とは独立して管理する。
  const [browserPermission, setBrowserPermission] = useState(
    typeof Notification !== "undefined" ? Notification.permission : null
  );
  // 2026-09-14新設: 「検索」タブに保存済みの正規表現条件。通知の
  // 実際の発火条件がユーザーから見て分かりにくい (「検索条件が
  // 空だと通知自体が飛ばない」という仕様がUI上どこにも書かれて
  // いなかった) という指摘を受け、現在の条件をこの画面にも表示する
  // ようにした (ユーザーとの合意事項)。
  const [searchExpression, setSearchExpression] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.getDiscordNotificationSettings(), api.getPickupSearch()])
      .then(([s, pickupSearch]) => {
        setWebhookUrl(s.webhook_url || "");
        setEnabled(s.enabled);
        setInAppEnabled(s.in_app_enabled || false);
        setBrowserEnabled(s.browser_enabled || false);
        setSearchExpression(pickupSearch.search_expression || "");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const result = await api.updateDiscordNotificationSettings({
        webhook_url: webhookUrl.trim(),
        enabled,
        in_app_enabled: inAppEnabled,
        browser_enabled: browserEnabled,
      });
      setWebhookUrl(result.webhook_url);
      setEnabled(result.enabled);
      setInAppEnabled(result.in_app_enabled);
      setBrowserEnabled(result.browser_enabled);
      setSavedAt(Date.now());
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  // 2026-09-15新設: ブラウザ通知トグルをONにする際、OS/ブラウザの
  // 通知許可がまだ下りていなければリクエストする。許可が拒否されて
  // いる場合はブラウザの設定画面から手動で変更してもらう必要がある
  // 旨を案内する (JavaScriptから再度ダイアログを出すことはできない
  // ため)。
  const handleBrowserEnabledToggle = async (checked) => {
    if (!checked) {
      setBrowserEnabled(false);
      return;
    }
    if (typeof Notification === "undefined") {
      // Web Notifications API非対応のブラウザ (一部のiOS Safari等)。
      // トグル自体はONにしておくが、実際の発火時にScanStatusContext
      // 側でNotification未対応を検知しトースト表示のみにフォール
      // バックする。
      setBrowserEnabled(true);
      return;
    }
    if (Notification.permission === "granted") {
      setBrowserEnabled(true);
      return;
    }
    if (Notification.permission === "denied") {
      // 既に拒否済みの場合、requestPermission()を呼んでもダイアログは
      // 出ない (ブラウザ側の制限)。トグルはONにするが、許可が無い旨は
      // 下のUIで案内する。
      setBrowserEnabled(true);
      return;
    }
    const permission = await Notification.requestPermission();
    setBrowserPermission(permission);
    setBrowserEnabled(true);
  };

  const sendTest = async () => {
    setTestResult(null);
    setTestSending(true);
    try {
      await api.testDiscordNotification();
      setTestResult({ ok: true, message: "テスト通知を送信しました。Discordのチャンネルを確認してください。" });
    } catch (e) {
      setTestResult({ ok: false, message: e.message });
    } finally {
      setTestSending(false);
    }
  };

  if (loading) {
    return <p className="text-center text-ink/30 text-sm py-8">読み込み中…</p>;
  }

  const hasSearchCondition = searchExpression.trim() !== "";
  const anyNotificationEnabled = enabled || inAppEnabled || browserEnabled;

  return (
    <div>
      <p className="text-xs text-ink/50 mb-4">
        「検索」タブに保存した条件にヒットする新着投稿が見つかったとき、Discord・アプリ内トースト・ブラウザ通知のいずれか（または複数）へ通知します。検索条件自体は「検索」タブで設定してください。
      </p>

      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      {/*
        2026-09-14新設、2026-09-15文言更新: 現在の通知発火条件を
        可視化する。検索条件が空の場合、いずれかの通知が有効になって
        いても実際には一切通知されない (「絞り込みなし」として
        無差別に全新着を通知しないための意図的な仕様) ため、通知が
        1つでも有効なときだけ強めの警告として表示する。
      */}
      <div className="bg-white border border-line rounded-xl p-3 mb-4">
        <p className="text-[11px] text-ink/40 mb-1">現在の通知条件（「検索」タブの内容）</p>
        {hasSearchCondition ? (
          <code className="block text-xs bg-paper rounded-lg px-2 py-1.5 text-ink/70 break-all">
            {searchExpression}
          </code>
        ) : (
          <p className="text-xs text-ink/40">未設定</p>
        )}
        {!hasSearchCondition && anyNotificationEnabled && (
          <div className="flex items-start gap-1.5 bg-alert/5 border border-alert/20 rounded-lg px-2.5 py-2 mt-2">
            <AlertTriangle size={13} className="text-alert shrink-0 mt-0.5" />
            <p className="text-[11px] text-alert">
              検索条件が未設定のため、通知は有効でも実際には一切送信されません。
              <Link to="/" className="underline font-bold">
                一覧の「検索」タブ
              </Link>
              で条件を設定してください。
            </p>
          </div>
        )}
      </div>

      {/*
        2026-09-15新設: アプリ内トースト通知・ブラウザ通知のトグル。
        Discordの設定 (Webhook URL) とは独立したセクションとして
        分ける (Webhook URLの入力欄と混同されないようにするため)。
      */}
      <div className="bg-white border border-line rounded-xl p-3 mb-4">
        <p className="text-xs font-bold text-ink/70 mb-2">アプリ内・ブラウザ通知</p>

        <label className="flex items-center gap-2 text-sm py-1.5">
          <input
            type="checkbox"
            checked={inAppEnabled}
            onChange={(e) => setInAppEnabled(e.target.checked)}
            className="accent-indigo"
          />
          <span className="text-ink/70">アプリ内トースト通知を有効にする</span>
        </label>
        <p className="text-[11px] text-ink/40 ml-6 mb-2">
          この画面を開いている間、対象の新着投稿が見つかると画面内にポップアップ表示します。
        </p>

        <label className="flex items-center gap-2 text-sm py-1.5">
          <input
            type="checkbox"
            checked={browserEnabled}
            onChange={(e) => handleBrowserEnabledToggle(e.target.checked)}
            className="accent-indigo"
          />
          <span className="text-ink/70">ブラウザ通知を有効にする</span>
        </label>
        <p className="text-[11px] text-ink/40 ml-6">
          ブラウザのタブを開いている間、OSの通知として表示します（タブを閉じている間は届きません）。
        </p>

        {browserEnabled && typeof Notification !== "undefined" && browserPermission === "denied" && (
          <div className="flex items-start gap-1.5 bg-alert/5 border border-alert/20 rounded-lg px-2.5 py-2 mt-2 ml-6">
            <BellOff size={13} className="text-alert shrink-0 mt-0.5" />
            <p className="text-[11px] text-alert">
              このブラウザで通知がブロックされています。ブラウザのサイト設定から通知を許可してください。
            </p>
          </div>
        )}
        {browserEnabled && typeof Notification !== "undefined" && browserPermission === "granted" && (
          <div className="flex items-center gap-1.5 text-ink/40 mt-2 ml-6">
            <Bell size={13} />
            <p className="text-[11px]">通知の許可を確認済みです。</p>
          </div>
        )}
        {browserEnabled && typeof Notification === "undefined" && (
          <div className="flex items-start gap-1.5 bg-alert/5 border border-alert/20 rounded-lg px-2.5 py-2 mt-2 ml-6">
            <AlertTriangle size={13} className="text-alert shrink-0 mt-0.5" />
            <p className="text-[11px] text-alert">
              このブラウザは通知に対応していないため、代わりにアプリ内トースト通知のみ表示されます。
            </p>
          </div>
        )}
      </div>

      <div className="bg-white border border-line rounded-xl p-3 mb-4">
        <p className="text-xs font-bold text-ink/70 mb-2">Discord通知</p>
        <label className="block text-sm text-ink/60 mb-1.5">Webhook URL</label>
        <input
          type="text"
          placeholder="https://discord.com/api/webhooks/..."
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          className="w-full bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
        />
        <p className="text-[11px] text-ink/40 mt-2">
          Discordのチャンネル設定「連携サービス」→「Webhookを作成」で発行されるURLを貼り付けてください。
        </p>

        <label className="flex items-center gap-2 text-sm mt-3">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="accent-indigo"
          />
          <span className="text-ink/70">Discord通知を有効にする</span>
        </label>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="w-full bg-indigo text-white rounded-xl py-2.5 text-sm font-bold disabled:opacity-50"
      >
        {saving ? "保存中…" : "保存する"}
      </button>
      {savedAt && (
        <p className="text-center text-[11px] text-ink/40 mt-2">保存しました</p>
      )}

      <button
        onClick={sendTest}
        disabled={testSending || !webhookUrl.trim()}
        className="w-full flex items-center justify-center gap-1.5 border border-line bg-white text-ink/70 rounded-xl py-2.5 text-sm font-bold disabled:opacity-40 mt-3"
      >
        <Send size={14} />
        {testSending ? "送信中…" : "Discordへテスト通知を送信"}
      </button>
      {testResult && (
        <p className={`text-center text-[11px] mt-2 ${testResult.ok ? "text-ink/40" : "text-alert"}`}>
          {testResult.message}
        </p>
      )}
    </div>
  );
}
