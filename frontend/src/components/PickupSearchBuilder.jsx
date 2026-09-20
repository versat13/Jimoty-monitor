import { useState, useEffect, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import {
  buildRegexFromWords,
  isValidRegex,
  parseWordsInput,
} from "../utils/pickupSearch";

/**
 * 「検索」タブの正規表現ビルダー + 生の正規表現入力欄 (2026-09-08新設)。
 *
 * ハイブリッド方式:
 * - 「含めたいワード」「除外したいワード」を入力すると、リアルタイムに
 *   正規表現を自動生成して下の生の正規表現欄に反映する。
 * - 生の正規表現欄は直接手直しできる。手直しした時点でビルダーとの
 *   自動同期を止める (isBuilderSynced=false)。以後はビルダー欄を
 *   操作しても正規表現欄が上書きされない。
 * - 「ビルダーに戻す」ボタンで、手直しを破棄してビルダーの入力から
 *   再生成した状態に戻せる。
 *
 * 保存内容はサーバー側DB (pickup_search テーブル) に永続化され、
 * 次回このツールを開いたときも自動的に復元される。
 */
export default function PickupSearchBuilder({ onSaved }) {
  const [includeInput, setIncludeInput] = useState("");
  const [excludeInput, setExcludeInput] = useState("");
  const [expression, setExpression] = useState("");
  const [isBuilderSynced, setIsBuilderSynced] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getPickupSearch()
      .then((s) => {
        setIncludeInput((s.include_words || []).join(", "));
        setExcludeInput((s.exclude_words || []).join(", "));
        setExpression(s.search_expression || "");
        setIsBuilderSynced(s.is_builder_synced ?? true);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  // ビルダー欄 (含める/除外ワード) の変更をリアルタイムに正規表現へ
  // 反映する。ただし「手直し済み」の状態 (isBuilderSynced=false) の
  // ときはビルダーを操作しても正規表現欄を上書きしない
  // (打ち合わせで合意した仕様)。
  useEffect(() => {
    if (!isBuilderSynced) return;
    const includeWords = parseWordsInput(includeInput);
    const excludeWords = parseWordsInput(excludeInput);
    setExpression(buildRegexFromWords(includeWords, excludeWords));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeInput, excludeInput]);

  const handleExpressionChange = (value) => {
    setExpression(value);
    setIsBuilderSynced(false);
  };

  const handleResetToBuilder = () => {
    const includeWords = parseWordsInput(includeInput);
    const excludeWords = parseWordsInput(excludeInput);
    setExpression(buildRegexFromWords(includeWords, excludeWords));
    setIsBuilderSynced(true);
  };

  const expressionValid = isValidRegex(expression);

  const save = async () => {
    if (!expressionValid) return;
    setError(null);
    setSaving(true);
    try {
      await api.updatePickupSearch({
        search_expression: expression,
        include_words: parseWordsInput(includeInput),
        exclude_words: parseWordsInput(excludeInput),
        is_builder_synced: isBuilderSynced,
      });
      setSavedAt(Date.now());
      onSaved?.(expression);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-center text-ink/30 text-sm py-8">読み込み中…</p>;
  }

  return (
    <div>
      {error && (
        <p className="text-xs text-alert bg-alert/5 border border-alert/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      <div className="bg-white border border-line rounded-xl p-3 mb-3">
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="text-[11px] text-ink/60">含めるワード（いずれか含む）</span>
            <input
              type="text"
              value={includeInput}
              onChange={(e) => setIncludeInput(e.target.value)}
              placeholder="iPhone, iPad"
              className="w-full mt-1 bg-paper border border-line rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
            />
            {/*
              2026-09-15追加: 区切り文字がカンマ(,)・読点(、)のみで、
              スペース区切りはOR検索にならない (1つのワードとして
              扱われてしまう) ことに気づきにくいという指摘を受け、
              入力欄の下に区切り文字と使い方の例を明記した。
              例:「メタルラック スチールラック」(空白区切り)は1つの
              ワードとして扱われOR検索にならないが、
              「メタルラック,スチールラック」(カンマ区切り)なら
              いずれかを含む投稿がヒットする。
            */}
            <span className="block text-[10px] text-ink/30 mt-1">
              カンマ（,）または読点（、）区切りでOR検索になります。例:
              メタルラック,スチールラック → どちらかを含む投稿がヒット
              （空白区切りは1つのワードとして扱われるため注意）
            </span>
          </label>

          <label className="block">
            <span className="text-[11px] text-ink/60">除外するワード</span>
            <input
              type="text"
              value={excludeInput}
              onChange={(e) => setExcludeInput(e.target.value)}
              placeholder="ジャンク, 訳あり"
              className="w-full mt-1 bg-paper border border-line rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo/30"
            />
            <span className="block text-[10px] text-ink/30 mt-1">
              こちらもカンマ（,）または読点（、）区切りで複数指定できます
            </span>
          </label>
        </div>
      </div>

      {/*
        2026-09-10変更: 「保存する」ボタンが全幅で大きすぎるという
        フィードバックを受け、正規表現欄の右横に幅1/3程度で設置する
        レイアウトに変更した (以前は正規表現欄の下に独立した全幅
        ボタンだった)。横幅を確保するため、正規表現欄とボタンを
        flexで横並びにする。
      */}
      <div className="bg-indigo/5 border-2 border-indigo/30 rounded-xl p-3 mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-bold text-indigo">正規表現（実際に使われる条件）</span>
          {!isBuilderSynced && (
            <button
              onClick={handleResetToBuilder}
              className="flex items-center gap-1 text-[11px] text-indigo hover:underline"
            >
              <RefreshCw size={11} />
              かんたん入力の内容に戻す
            </button>
          )}
        </div>
        <div className="flex items-stretch gap-2">
          <input
            type="text"
            value={expression}
            onChange={(e) => handleExpressionChange(e.target.value)}
            placeholder="未設定（絞り込みなし）"
            className={`flex-1 min-w-0 bg-white border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 ${
              expressionValid
                ? "border-indigo/40 focus:ring-indigo/30"
                : "border-alert focus:ring-alert/30"
            }`}
          />
          <button
            onClick={save}
            disabled={saving || !expressionValid}
            className="basis-1/3 shrink-0 bg-indigo text-white rounded-lg px-2 text-sm font-bold disabled:opacity-50"
          >
            {saving ? "保存中…" : "保存する"}
          </button>
        </div>
        {!expressionValid && (
          <p className="text-[11px] text-alert mt-1">正規表現として不正です。</p>
        )}
        {!isBuilderSynced && expressionValid && (
          <p className="text-[11px] text-ink/40 mt-1">
            手直しされています。かんたん入力を変更しても、この内容は上書きされません。
          </p>
        )}
        {savedAt && <p className="text-[11px] text-ink/40 mt-1">保存しました</p>}
      </div>
    </div>
  );
}
