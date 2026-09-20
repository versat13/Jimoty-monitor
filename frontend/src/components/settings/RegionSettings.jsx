import { useState, useEffect, useCallback } from "react";
import { Loader2, Download } from "lucide-react";
import { api } from "../../api/client";
import { PREFECTURES } from "../../utils/prefectures";

// ---------------------------------------------------------------------
// 監視対象の地域設定 (2026-09-10 新設、2026-09-12 動的取得対応)
//
// これまで監視対象の都道府県・市区町村はコード側の決め打ち値
// (福岡県北九州市) しか存在せず、変更するUIが無かった。ログ調査の
// 結果、area_id/area_nameが未設定のまま(=福岡県全域)巡回してしまう
// 不具合も見つかったため (根本原因は別途 repository/
// scan_settings_repository.py 側で修正済み)、変更できるUI自体も
// 追加することになった。
//
// 都道府県は主要47都道府県の固定プルダウン。市区町村は当初
// 自由テキスト入力のみだったが、2026-09-12に「公式から市区町村を
// 取得する」ボタンを追加した。押すと実際にジモティーへアクセスして
// 市区町村候補 (area_id/area_name) を取得しDBにキャッシュする
// (scraper.area_list_parser参照)。取得済みの都道府県を選ぶと市区町村が
// プルダウン選択式になる。まだ取得していない都道府県では、従来通り
// 自由テキスト入力のままにしておく (取得は都道府県ごとに1回、
// ユーザーの明示的なボタン操作でのみ行う設計)。
// ---------------------------------------------------------------------

export default function RegionSettings() {
  const [prefecture, setPrefecture] = useState("fukuoka");
  const [areaId, setAreaId] = useState("");
  const [areaName, setAreaName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  // 2026-09-12新設: 市区町村候補 (都道府県ごとにキャッシュ取得)。
  // areaOptionsがnullの間は「まだ確認していない/読み込み中」、
  // 空配列は「取得済みだが候補が無い(=自由入力のまま)」を表す。
  const [areaOptions, setAreaOptions] = useState(null);
  const [areaOptionsFetchedAt, setAreaOptionsFetchedAt] = useState(null);
  const [fetchingAreas, setFetchingAreas] = useState(false);
  const [fetchAreasError, setFetchAreasError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getRegionSettings()
      .then((s) => {
        setPrefecture(s.prefecture);
        setAreaId(s.area_id ?? "");
        setAreaName(s.area_name ?? "");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  // 2026-09-12新設: 都道府県が変わるたびに、その都道府県の市区町村
  // キャッシュ (既に取得済みかどうか) を読みに行く。
  const loadAreaOptions = useCallback((pref) => {
    setAreaOptions(null);
    setFetchAreasError(null);
    api
      .getAreaOptions(pref)
      .then((res) => {
        setAreaOptions(res.options);
        setAreaOptionsFetchedAt(res.fetched_at);
      })
      .catch(() => {
        // 2026-09-12: キャッシュ確認自体の失敗は致命的でない
        // (自由入力にフォールバックできるため)、エラー表示はしない。
        setAreaOptions([]);
        setAreaOptionsFetchedAt(null);
      });
  }, []);

  useEffect(() => {
    if (!loading) loadAreaOptions(prefecture);
  }, [prefecture, loading, loadAreaOptions]);

  const handleFetchAreas = async () => {
    setFetchingAreas(true);
    setFetchAreasError(null);
    try {
      const res = await api.fetchAreaOptions(prefecture);
      setAreaOptions(res.options);
      setAreaOptionsFetchedAt(res.fetched_at);
    } catch (e) {
      setFetchAreasError(e.message);
    } finally {
      setFetchingAreas(false);
    }
  };

  // area_id/area_nameは「両方指定」か「両方空欄 (都道府県全域)」の
  // どちらかである必要がある (api/main.py update_region_settings_endpoint
  // 参照)。保存前にフロント側でも軽く検証し、片方だけ入力した状態での
  // 送信を防ぐ。
  const partiallyFilled = Boolean(areaId.trim()) !== Boolean(areaName.trim());

  const save = async () => {
    setError(null);
    if (partiallyFilled) {
      setError("市区町村ID・市区町村名は両方入力するか、両方空欄にしてください。");
      return;
    }
    setSaving(true);
    try {
      await api.updateRegionSettings({
        prefecture,
        area_id: areaId.trim() || null,
        area_name: areaName.trim() || null,
      });
      setSavedAt(Date.now());
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-center text-ink/30 text-sm py-8">読み込み中…</p>;
  }

  // 候補が取得済み(1件以上)ならプルダウン選択式、そうでなければ
  // 従来通り自由テキスト入力にする。
  const hasAreaOptions = Array.isArray(areaOptions) && areaOptions.length > 0;

  return (
    <div>
      <p className="text-xs text-ink/50 mb-4">
        巡回対象の都道府県・市区町村を設定します。市区町村を空欄にすると、都道府県全域を対象に巡回します。
      </p>

      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      <div className="bg-white border border-line rounded-xl p-3 mb-4 space-y-3">
        <label className="block text-sm">
          <span className="text-ink/60 block mb-1">都道府県</span>
          <select
            value={prefecture}
            onChange={(e) => {
              setPrefecture(e.target.value);
              // 2026-09-12: 都道府県を切り替えたら、それまで入力して
              // いた市区町村は一旦クリアする (別の都道府県のIDを
              // 引き継いでしまうと不整合になるため)。
              setAreaId("");
              setAreaName("");
            }}
            className="w-full bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
          >
            {PREFECTURES.map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        {/*
          2026-09-12新設: 「公式から市区町村を取得する」ボタン。
          都道府県プルダウンの直下に配置する (ユーザーとの合意事項)。
        */}
        <div>
          <button
            onClick={handleFetchAreas}
            disabled={fetchingAreas}
            className="w-full flex items-center justify-center gap-1.5 text-xs font-bold text-indigo border border-indigo/30 rounded-lg py-2 disabled:opacity-50"
          >
            {fetchingAreas ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Download size={13} />
            )}
            {fetchingAreas ? "取得中…" : "公式から市区町村を取得する"}
          </button>
          {areaOptionsFetchedAt && (
            <p className="text-[11px] text-ink/40 mt-1 text-center">
              {hasAreaOptions
                ? `${areaOptions.length}件の市区町村を取得済み`
                : "市区町村の取得結果が0件でした"}
            </p>
          )}
          {fetchAreasError && (
            <p className="text-[11px] text-alert mt-1">{fetchAreasError}</p>
          )}
        </div>

        {hasAreaOptions ? (
          <label className="block text-sm">
            <span className="text-ink/60 block mb-1">市区町村</span>
            <select
              value={areaId || ""}
              onChange={(e) => {
                const selected = areaOptions.find((o) => o.area_id === e.target.value);
                if (!selected) {
                  // 「都道府県全域」を選んだ場合
                  setAreaId("");
                  setAreaName("");
                } else {
                  setAreaId(selected.area_id);
                  setAreaName(selected.area_name);
                }
              }}
              className="w-full bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
            >
              <option value="">（都道府県全域・市区町村を絞らない）</option>
              {areaOptions.map((o) => (
                <option key={o.area_id} value={o.area_id}>
                  {o.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <>
            <label className="block text-sm">
              <span className="text-ink/60 block mb-1">市区町村ID（任意）</span>
              <input
                type="text"
                value={areaId}
                onChange={(e) => setAreaId(e.target.value)}
                placeholder="例: 731"
                className="w-full bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
              />
            </label>

            <label className="block text-sm">
              <span className="text-ink/60 block mb-1">市区町村名（ローマ字・任意）</span>
              <input
                type="text"
                value={areaName}
                onChange={(e) => setAreaName(e.target.value)}
                placeholder="例: kitakyushu"
                className="w-full bg-paper border border-line rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
              />
            </label>

            <p className="text-[11px] text-ink/40">
              上の「公式から市区町村を取得する」ボタンを押すとプルダウン選択に切り替わります。
              手入力する場合は、ジモティーの一覧ページURL
              （例: https://jmty.jp/fukuoka/sale-all/a-731-kitakyushu）の
              「a-{"{ID}"}-{"{ローマ字名}"}」部分から調べて入力してください。
              両方空欄にすると市区町村を絞らず、都道府県全域を対象にします。
            </p>
          </>
        )}
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
    </div>
  );
}
