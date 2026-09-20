import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import KeywordSettings from "../components/settings/KeywordSettings";
import CategorySettings from "../components/settings/CategorySettings";
import SellerRuleSettings from "../components/settings/SellerRuleSettings";
import RegionSettings from "../components/settings/RegionSettings";
import ScanRangeSettings from "../components/settings/ScanRangeSettings";
import AutoRefreshSettings from "../components/settings/AutoRefreshSettings";
import DiscordNotificationSettings from "../components/settings/DiscordNotificationSettings";
import BackupSettings from "../components/settings/BackupSettings";
import DeletedArticlesLog from "../components/settings/DeletedArticlesLog";
import ResetSettings from "../components/settings/ResetSettings";

// 2026-09-14変更: タブ数が8個に増え、画面幅の狭い端末で1行に
// 収まらず折り返して読みにくくなっていたため、2階層タブに再編した
// (ユーザーとの合意事項)。各タブにgroupを持たせ、上段でグループを
// 選ぶと下段に該当タブが展開される。
//   - フィルタ: 一覧の表示・非表示を制御する設定
//   - 巡回設定: どう情報を取得し、どう知らせるかの設定
//   - データ: 保存データそのものの管理
// URL構造 (/settings/:tab) は変更していない。tabキーからgroupを
// 逆引きする方式にすることで、既存の外部リンク
// (ArticleListHeader.jsxの「自動更新の設定」ボタン等、
// /settings/auto-refresh のように特定タブへ直接遷移するもの) を
// 変更せずに済むようにしている。
const GROUPS = [
  { key: "filter", label: "フィルタ" },
  { key: "scan", label: "巡回設定" },
  { key: "data", label: "データ" },
];

const TABS = [
  { key: "keywords", label: "NGワード", group: "filter" },
  { key: "categories", label: "NGカテゴリ", group: "filter" },
  { key: "sellers", label: "ユーザー", group: "filter" },
  { key: "scan-range", label: "取得範囲", group: "scan" },
  { key: "region", label: "地域", group: "scan" },
  { key: "auto-refresh", label: "自動更新", group: "scan" },
  { key: "discord-notification", label: "通知", group: "scan" },
  { key: "backup", label: "バックアップ", group: "data" },
  { key: "deleted-log", label: "削除履歴", group: "data" },
  { key: "reset", label: "リセット", group: "data" },
];

const DEFAULT_TAB = "keywords";

export default function SettingsPage() {
  // 2026-09-10変更: タブ状態をuseStateではなくURLパス (/settings/:tab)
  // で管理するようにした。これにより、
  //   - 一覧画面の設定ボタンから「自動更新」タブへ直接遷移できる
  //     (navigate("/settings/auto-refresh"))
  //   - ブラウザの戻る/進むやリロードでもタブの状態が保たれる
  // 以前はSettingsPageが常にトップタブ(NGワード)で開始していた
  // (URLでタブを区別していなかったため)。
  const { tab: tabParam } = useParams();
  const navigate = useNavigate();

  // 不正/未指定のタブキーが来た場合はデフォルトタブとして扱う
  // (存在しないタブでmainが空になるのを防ぐ)。URL自体は正規化しない
  // (例えば /settings のような旧リンクを踏んでも一覧テキストの
  // 表示が壊れないようにするための緩いフォールバックに留める)。
  const isValidTab = TABS.some((t) => t.key === tabParam);
  const tab = isValidTab ? tabParam : DEFAULT_TAB;
  const activeTab = TABS.find((t) => t.key === tab) ?? TABS[0];
  const activeGroup = activeTab.group;

  const setTab = useCallback(
    (nextTab) => {
      navigate(`/settings/${nextTab}`, { replace: true });
    },
    [navigate]
  );

  // 2026-09-14新設: グループボタンを押したら、そのグループの先頭タブへ
  // 遷移する (「フィルタを開いたらまずNGワードが見える」という
  // 自然な挙動にするため)。既に選択中のグループを再度押した場合も
  // 先頭タブに戻る (グループ内のどのタブにいても、グループボタンを
  // 押せば先頭タブに戻れるという分かりやすさを優先した)。
  const changeGroup = (groupKey) => {
    const firstTabInGroup = TABS.find((t) => t.group === groupKey);
    if (firstTabInGroup) setTab(firstTabInGroup.key);
  };

  const tabsInActiveGroup = TABS.filter((t) => t.group === activeGroup);

  // 2026-09-09新設: NGカテゴリ画面の入力フォームをsticky表示する際、
  // 上に重なるheaderの実測高さ分だけ空けるために使う (固定px決め打ち
  // だとheaderの内容量やフォントサイズ変更で簡単にズレるため、
  // 実測値を使う方式にした)。
  const headerRef = useRef(null);
  const [headerHeight, setHeaderHeight] = useState(0);

  useEffect(() => {
    if (!headerRef.current) return;
    const el = headerRef.current;
    const observer = new ResizeObserver(() => setHeaderHeight(el.offsetHeight));
    observer.observe(el);
    setHeaderHeight(el.offsetHeight);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="max-w-xl mx-auto pb-24">
      <header
        ref={headerRef}
        className="sticky top-0 z-10 bg-paper/95 backdrop-blur px-4 pt-5 pb-3 border-b border-line"
      >
        <h1 className="font-display font-black text-xl tracking-tight">設定</h1>

        {/* 上段: グループ選択 */}
        <div className="flex gap-1 mt-3 bg-line/50 rounded-full p-1">
          {GROUPS.map((g) => (
            <button
              key={g.key}
              onClick={() => changeGroup(g.key)}
              className={`flex-1 text-xs font-bold py-1.5 rounded-full transition-colors ${
                activeGroup === g.key ? "bg-white text-indigo shadow-sm" : "text-ink/40"
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>

        {/* 下段: 選択中グループ内のタブ */}
        <div className="flex gap-1 mt-2">
          {tabsInActiveGroup.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 text-xs font-bold py-1.5 rounded-full transition-colors ${
                tab === t.key ? "bg-indigo/10 text-indigo" : "text-ink/40"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <main className="px-4 pt-4">
        {tab === "keywords" && <KeywordSettings />}
        {tab === "categories" && <CategorySettings stickyTop={headerHeight} />}
        {tab === "sellers" && <SellerRuleSettings />}
        {tab === "region" && <RegionSettings />}
        {tab === "scan-range" && <ScanRangeSettings />}
        {tab === "auto-refresh" && <AutoRefreshSettings />}
        {tab === "discord-notification" && <DiscordNotificationSettings />}
        {tab === "backup" && <BackupSettings />}
        {tab === "deleted-log" && <DeletedArticlesLog />}
        {tab === "reset" && <ResetSettings />}
      </main>
    </div>
  );
}

