import { useState, useEffect, useCallback } from "react";
import { Plus, X } from "lucide-react";
import { api } from "../../api/client";

// NGカテゴリの階層区別 (2026-09-08 新設)
//
// ジモティーのカテゴリは「大カテゴリ (sale-XXXのURLスラッグ)」
// 「ジャンル (g-数字)」「サブジャンル (g-数字、ジャンルのさらに配下)」
// の3階層がある。大カテゴリ・ジャンルを選べば配下すべてがNGになる、
// という仕様のため、登録時にどの階層かを明示する
// (repository/pickup_search... ではなく filters/category_filter.py
// 参照。バックエンドのcategory_levelと対応する)。
// 2026-09-08調整: 大カテゴリ・ジャンルの接頭語も色分けし、サジェスト側の
// 強調 (大カテゴリ=塗りつぶし、ジャンル=枠線のみ) と一貫させる。
const CATEGORY_LEVEL_LABEL = {
  parent: "カテゴリ",
  mid: "ジャンル",
  leaf: "サブ",
};

const CATEGORY_LEVEL_LABEL_CLASS = {
  parent: "text-indigo font-bold",
  mid: "text-indigo/70 font-bold",
  leaf: "text-ink/40",
};

/**
 * /api/categories/used が返すフラットな配列 (parent/mid/leafが混在) を、
 * 表示用に「大カテゴリ→ジャンル→サブジャンル」の完全な入れ子構造に
 * 組み立て直す (2026-09-09拡張)。
 *
 * 従来は大カテゴリをフラットに並べ、ジャンル・サブジャンルを別グループ
 * として並べる2段構成だったが、ユーザー要望「大カテゴリの中にジャンル、
 * その中にサブジャンルという並びにしたい」を受けて、大カテゴリ配下に
 * ジャンルをぶら下げる完全な入れ子構造に変更した。
 * (/api/categories/used がジャンルにも親の大カテゴリ情報
 * parent_id/parent_nameを返すようになったため実現可能になった)。
 *
 * どの大カテゴリにも属さないジャンル・サブジャンル (親情報が無い、
 * または対応する親がリストに見つからない) は「所属不明」として
 * 末尾にまとめる。
 */
function groupUsedCategories(usedCategories) {
  const parents = usedCategories.filter((c) => c.category_level === "parent");
  const mids = usedCategories.filter((c) => c.category_level === "mid");
  const leaves = usedCategories.filter((c) => c.category_level === "leaf");

  // ジャンルごとに、そのジャンルに属するサブジャンルをまとめる。
  const midsWithChildren = mids.map((mid) => ({
    mid,
    children: leaves.filter((leaf) => leaf.parent_mid_id === mid.category_id),
  }));

  // 大カテゴリごとに、そのカテゴリに属するジャンル(+配下サブジャンル)をまとめる。
  const parentGroups = parents.map((parent) => ({
    parent,
    midGroups: midsWithChildren.filter((mg) => mg.mid.parent_id === parent.category_id),
  }));

  // どの大カテゴリにも属さないジャンル (親情報が無い、または対応する
  // 親がparentsに見つからない)。
  const orphanMidGroups = midsWithChildren.filter(
    (mg) => !mg.mid.parent_id || !parents.some((p) => p.category_id === mg.mid.parent_id)
  );

  // どのジャンルにも属さないサブジャンル。
  const orphanLeaves = leaves.filter(
    (leaf) => !mids.some((mid) => mid.category_id === leaf.parent_mid_id)
  );

  return { parentGroups, orphanMidGroups, orphanLeaves };
}

/**
 * 2026-09-09新設: NGカテゴリ登録済みのカテゴリ・その配下を判定する
 * ヘルパー群。「一律のルール」(=opacityを下げるだけ) にすることで、
 * 大カテゴリ・ジャンル・サブジャンルそれぞれに個別の暗転色を持たせず、
 * 保守を楽にする (ユーザー方針)。
 *
 * 大カテゴリがNG登録されていれば、配下のジャンル・サブジャンルも
 * 連動して暗く表示する (filters/category_filter.pyの階層判定ロジック
 * と考え方を揃えている)。
 */
function buildNgStatusChecker(registeredItems) {
  const parentIds = new Set(
    registeredItems.filter((i) => i.category_level === "parent").map((i) => i.category_id)
  );
  const midIds = new Set(
    registeredItems.filter((i) => i.category_level === "mid").map((i) => i.category_id)
  );
  const leafIds = new Set(
    registeredItems.filter((i) => i.category_level === "leaf").map((i) => i.category_id)
  );

  return {
    isParentNg: (parent) => parentIds.has(parent.category_id),
    isMidNg: (mid) => midIds.has(mid.category_id) || (mid.parent_id && parentIds.has(mid.parent_id)),
    isLeafNg: (leaf, parentMid) =>
      leafIds.has(leaf.category_id) ||
      (leaf.parent_mid_id && midIds.has(leaf.parent_mid_id)) ||
      (parentMid && parentMid.parent_id && parentIds.has(parentMid.parent_id)),
  };
}

// 2026-09-09新設: NG適用済みのカテゴリボタンに一律で使う暗転スタイル。
// 個別の色分けを増やさず、常にこのopacityだけを足す方針
// (ユーザー方針:「一律のルールにしたい」「保守に不便」)。
const NG_APPLIED_CLASS = "opacity-30 pointer-events-none";

export default function CategorySettings({ stickyTop = 0 }) {
  const [items, setItems] = useState([]);
  const [categoryId, setCategoryId] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [categoryLevel, setCategoryLevel] = useState("leaf");
  const [error, setError] = useState(null);
  // 2026-09-04新設: DBに実在する投稿から抽出したカテゴリ候補
  // (サジェスト用)。カテゴリマスタが存在しないため、あくまで
  // 「このソフトが過去に見た投稿が使っていたカテゴリ」の一覧であり、
  // 網羅性は保証しない。手打ち入力自体は引き続き可能。
  const [usedCategories, setUsedCategories] = useState([]);

  const load = useCallback(() => {
    api.listNgCategories().then(setItems).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    api.listUsedCategories().then(setUsedCategories).catch(() => setUsedCategories([]));
  }, []);

  const add = async () => {
    if (!categoryId.trim()) return;
    try {
      await api.createNgCategory(categoryId.trim(), categoryName.trim() || null, categoryLevel);
      setCategoryId("");
      setCategoryName("");
      setCategoryLevel("leaf");
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  const pickSuggestion = (c) => {
    setCategoryId(c.category_id);
    setCategoryName(c.category_name || "");
    setCategoryLevel(c.category_level);
  };

  // 2026-09-09変更: 従来は登録済みのカテゴリIDをサジェストから除外
  // していたが、ユーザー要望により「消さず、見た目を暗くする」方式に
  // 変更した。除外せず全件を候補として扱い、表示側でNG判定する。
  const { parentGroups, orphanMidGroups, orphanLeaves } = groupUsedCategories(usedCategories);
  const ngStatus = buildNgStatusChecker(items);

  return (
    <div>
      {/*
        2026-09-09調整: 入力フォーム部分をスクロール対象から外し、常に
        画面上部に表示され続けるようにする (ユーザー要望:
        「NGワード入力フォームはスクロールバーの対象外にしてください」)。
        SettingsPageのheaderと同様sticky指定にし、その下の候補一覧
        (縦に長くなりがちな部分) だけがページスクロールに応じて流れる
        構成にしている。
      */}
      <div
        className="sticky z-[5] bg-paper pt-1 pb-2 -mx-4 px-4"
        style={{ top: stickyTop }}
      >
        <p className="text-xs text-ink/50 mb-3">
          カテゴリ・ジャンル・サブジャンルを指定して除外します。カテゴリを選べば配下すべて、ジャンルを選べばそのジャンルと配下のサブジャンルすべてがNGになります。
        </p>

        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            <select
              value={categoryLevel}
              onChange={(e) => setCategoryLevel(e.target.value)}
              className="bg-white border border-line rounded-xl px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
            >
              <option value="parent">カテゴリ</option>
              <option value="mid">ジャンル</option>
              <option value="leaf">サブ</option>
            </select>
            <input
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              placeholder="ID（例: oth）"
              className="flex-1 bg-white border border-line rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
            />
          </div>
          <div className="flex gap-2">
            <input
              value={categoryName}
              onChange={(e) => setCategoryName(e.target.value)}
              placeholder="表示名（任意）"
              className="flex-1 bg-white border border-line rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
            />
            <button
              onClick={add}
              className="bg-indigo text-white rounded-xl px-3 flex items-center justify-center"
            >
              <Plus size={18} />
            </button>
          </div>
        </div>

        {error && <p className="text-alert text-xs mt-2">{error}</p>}
      </div>

      {/*
        2026-09-04新設、2026-09-08/09拡張: 過去に監視した投稿から実際に
        使われているカテゴリをサジェストとして表示する。クリックすると
        上の入力欄に反映されるだけで、登録自体は「＋」ボタンを押すまで
        行わない (誤クリックでの即時登録を避けるため)。

        表示順序 (2026-09-09変更): 大カテゴリ→その中のジャンル→さらに
        その中のサブジャンル、という完全な入れ子構造にした (ユーザー
        要望:「大カテゴリ、大カテゴリの中のジャンル、さらにその中の
        サブジャンルという並びにできますか」)。

        NG適用済みの表示 (2026-09-09変更): 従来は登録済みのカテゴリを
        候補から消していたが、「消さず見た目を暗くする」方式に変更。
        大カテゴリ・ジャンル・サブジャンルいずれも同じ NG_APPLIED_CLASS
        (opacity低下+クリック無効) の一律ルールを適用する。大カテゴリが
        NGなら配下のジャンル・サブジャンルも連動して暗くなる
        (buildNgStatusChecker参照)。ユーザー方針:「色を少し暗くする、
        というルールにしてしまうとそれぞれの色分けに対してさらに個別で
        分けなきゃならないのが今後の保守に不便」。
      */}
      <div className="mt-3">
        {(parentGroups.length > 0 || orphanMidGroups.length > 0 || orphanLeaves.length > 0) && (
          <div className="flex flex-col gap-2.5">
            {parentGroups.map(({ parent, midGroups }) => {
              const parentNg = ngStatus.isParentNg(parent);
              return (
                <div key={`parent-${parent.category_id}`} className="flex flex-col gap-1.5">
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      onClick={() => pickSuggestion(parent)}
                      disabled={parentNg}
                      className={`text-xs font-bold bg-indigo text-white border-2 border-indigo rounded-full px-2.5 py-1 hover:bg-indigo/90 transition-colors ${
                        parentNg ? NG_APPLIED_CLASS : ""
                      }`}
                      title={`category_id: ${parent.category_id}`}
                    >
                      {parent.category_name || parent.category_id}
                    </button>
                  </div>

                  {midGroups.length > 0 && (
                    <div className="flex flex-col gap-1.5 pl-3 border-l-2 border-line">
                      {midGroups.map(({ mid, children }) => {
                        const midNg = parentNg || ngStatus.isMidNg(mid);
                        return (
                          <div
                            key={`mid-${mid.category_id}`}
                            className="flex flex-wrap items-center gap-1.5"
                          >
                            <button
                              onClick={() => pickSuggestion(mid)}
                              disabled={midNg}
                              className={`text-xs font-bold bg-white text-indigo border border-indigo rounded-full px-2.5 py-1 hover:bg-indigo/5 transition-colors ${
                                midNg ? NG_APPLIED_CLASS : ""
                              }`}
                              title={`category_id: ${mid.category_id}`}
                            >
                              {mid.category_name || mid.category_id}
                            </button>
                            {children.map((leaf) => {
                              const leafNg = midNg || ngStatus.isLeafNg(leaf, mid);
                              return (
                                <button
                                  key={`leaf-${leaf.category_id}`}
                                  onClick={() => pickSuggestion(leaf)}
                                  disabled={leafNg}
                                  className={`text-xs bg-line/50 hover:bg-line text-ink/60 rounded-full px-2.5 py-1 transition-colors ${
                                    leafNg ? NG_APPLIED_CLASS : ""
                                  }`}
                                  title={`category_id: ${leaf.category_id}`}
                                >
                                  {leaf.category_name || leaf.category_id}
                                </button>
                              );
                            })}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {/* どの大カテゴリにも属さないジャンル (+配下サブジャンル) */}
            {orphanMidGroups.map(({ mid, children }) => {
              const midNg = ngStatus.isMidNg(mid);
              return (
                <div key={`orphan-mid-${mid.category_id}`} className="flex flex-wrap items-center gap-1.5">
                  <button
                    onClick={() => pickSuggestion(mid)}
                    disabled={midNg}
                    className={`text-xs font-bold bg-white text-indigo border border-indigo rounded-full px-2.5 py-1 hover:bg-indigo/5 transition-colors ${
                      midNg ? NG_APPLIED_CLASS : ""
                    }`}
                    title={`category_id: ${mid.category_id}`}
                  >
                    {mid.category_name || mid.category_id}
                  </button>
                  {children.map((leaf) => {
                    const leafNg = midNg || ngStatus.isLeafNg(leaf, mid);
                    return (
                      <button
                        key={`leaf-${leaf.category_id}`}
                        onClick={() => pickSuggestion(leaf)}
                        disabled={leafNg}
                        className={`text-xs bg-line/50 hover:bg-line text-ink/60 rounded-full px-2.5 py-1 transition-colors ${
                          leafNg ? NG_APPLIED_CLASS : ""
                        }`}
                        title={`category_id: ${leaf.category_id}`}
                      >
                        {leaf.category_name || leaf.category_id}
                      </button>
                    );
                  })}
                </div>
              );
            })}

            {orphanLeaves.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {orphanLeaves.map((leaf) => {
                  const leafNg = ngStatus.isLeafNg(leaf, null);
                  return (
                    <button
                      key={`orphan-leaf-${leaf.category_id}`}
                      onClick={() => pickSuggestion(leaf)}
                      disabled={leafNg}
                      className={`text-xs bg-line/50 hover:bg-line text-ink/60 rounded-full px-2.5 py-1 transition-colors ${
                        leafNg ? NG_APPLIED_CLASS : ""
                      }`}
                      title={`category_id: ${leaf.category_id}`}
                    >
                      {leaf.category_name || leaf.category_id}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2 mt-4">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between bg-white border border-line rounded-xl px-3 py-2"
          >
            <span className="text-sm font-medium">
              <span className={`text-xs mr-1 ${CATEGORY_LEVEL_LABEL_CLASS[item.category_level] || "text-ink/40"}`}>
                {CATEGORY_LEVEL_LABEL[item.category_level] || "サブ"}：
              </span>
              {item.category_name || item.category_id}
              <span className="text-ink/30 ml-1 font-mono text-xs">({item.category_id})</span>
            </span>
            <button
              onClick={() => api.deleteNgCategory(item.id).then(load)}
              className="text-ink/30 hover:text-alert"
            >
              <X size={16} />
            </button>
          </div>
        ))}
        {items.length === 0 && (
          <p className="text-center text-ink/30 text-sm py-8">NGカテゴリは未登録です</p>
        )}
      </div>
    </div>
  );
}

