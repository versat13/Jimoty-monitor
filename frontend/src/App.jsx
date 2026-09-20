import { BrowserRouter, Routes, Route } from "react-router-dom";
import ArticleListPage from "./pages/ArticleListPage";
import SettingsPage from "./pages/SettingsPage";
import BottomNav from "./components/BottomNav";
import ToastContainer from "./components/ToastContainer";
import { ScanStatusProvider } from "./context/ScanStatusContext";

export default function App() {
  return (
    <BrowserRouter>
      {/*
        2026-09-10追加: 巡回状態 (手動・自動を問わず「今スキャン中か」
        「前回/次回更新はいつか」) を一覧・設定・BottomNavのどこからでも
        参照できるよう、Router全体をScanStatusProviderで包む。
      */}
      <ScanStatusProvider>
        <div className="min-h-screen bg-paper">
          {/*
            2026-09-15追加: アプリ内トースト通知。「検索」タブの条件に
            ヒットした新着投稿が見つかったときにポップアップ表示する
            (通知の検知・発火ロジックはScanStatusContext側が担う)。
            どの画面にいても表示されるよう、Routesの外・画面全体に
            対してfixed配置するToastContainerをここに置く。
          */}
          <ToastContainer />
          <Routes>
            <Route path="/" element={<ArticleListPage />} />
            {/*
              2026-08-26: 投稿詳細をページ遷移からモーダル表示に変更した。
              URLは "/articles/:articleId" のまま維持し (リンク共有・
              ブラウザの戻るボタンを機能させるため)、実際のレンダリングは
              ArticleListPage が担う。一覧の背後にモーダルを重ねる形。
            */}
            <Route path="/articles/:articleId" element={<ArticleListPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            {/*
              2026-09-10追加: 設定画面のタブをURLパスで区別できるように
              した (/settings/keywords, /settings/auto-refresh 等)。
              以前は設定画面への導線が常にトップタブ(NGワード)に着地して
              いたが、一覧画面の設定ボタンから「自動更新」タブへ直接
              遷移させたい要望があり追加した。タブの検証・デフォルト
              フォールバックはSettingsPage側で行う。
            */}
            <Route path="/settings/:tab" element={<SettingsPage />} />
          </Routes>
          <BottomNav />
        </div>
      </ScanStatusProvider>
    </BrowserRouter>
  );
}
