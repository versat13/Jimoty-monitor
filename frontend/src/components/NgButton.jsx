import { useState, useRef, useEffect } from "react";
import { Ban, Type, User } from "lucide-react";
import NgRegisterModal from "./NgRegisterModal";

/**
 * NGボタン (🚫)。WatchButton (☆) と対になる操作。
 *
 * 2026-08-26新設。クリックすると「NGワードとして登録」「この出品者を
 * NG登録」の2択ポップオーバーが出て、選んだ種別の登録モーダル
 * (NgRegisterModal) を開く。設定画面から独立して、その場で見ている
 * 投稿から直接NG登録できるようにする目的。
 *
 * 出品者が存在しない投稿 (seller_id が無い) の場合は
 * 「NGユーザーとして登録」の選択肢を出さない。
 */
export default function NgButton({ article, size = 16 }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [modalMode, setModalMode] = useState(null); // "keyword" | "seller" | null
  const [menuAlign, setMenuAlign] = useState("right"); // "right" | "left"
  const menuRef = useRef(null);
  const buttonRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [menuOpen]);

  // 2026-08-28: テーブルモードで画面左寄りにNGボタンがある場合、
  // メニューをright-0(ボタンの右端に揃えて左方向へ伸ばす)で固定すると
  // 画面外にはみ出して見切れる不具合があった。ボタンの画面上の位置を
  // 見て、メニュー幅(224px=w-56)を表示するスペースが左側に無ければ
  // 右方向に開く(left-0)よう自動判定する。
  const MENU_WIDTH = 224;
  const openMenu = (e) => {
    e.stopPropagation();
    if (!menuOpen && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      setMenuAlign(rect.right - MENU_WIDTH < 8 ? "left" : "right");
    }
    setMenuOpen((v) => !v);
  };

  const choose = (mode) => (e) => {
    e.stopPropagation();
    setMenuOpen(false);
    setModalMode(mode);
  };

  return (
    <div className="relative inline-block" ref={menuRef}>
      <button
        ref={buttonRef}
        onClick={openMenu}
        title="NG登録"
        className="text-ink/25 hover:text-alert transition-colors"
      >
        <Ban size={size} />
      </button>

      {menuOpen && (
        <div
          className={`absolute ${menuAlign === "right" ? "right-0" : "left-0"} mt-1 bg-white border border-line rounded-xl shadow-card p-1 z-20 w-56 text-sm`}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={choose("keyword")}
            className="w-full flex items-center gap-2 px-2.5 py-2 hover:bg-paper rounded-lg text-left whitespace-nowrap"
          >
            <Type size={14} className="text-ink/40 shrink-0" />
            NGワードとして登録
          </button>
          {article.seller_id && (
            <button
              onClick={choose("seller")}
              className="w-full flex items-center gap-2 px-2.5 py-2 hover:bg-paper rounded-lg text-left whitespace-nowrap"
            >
              <User size={14} className="text-ink/40 shrink-0" />
              この出品者をNG登録
            </button>
          )}
        </div>
      )}

      {modalMode && (
        <NgRegisterModal
          mode={modalMode}
          article={article}
          onClose={() => setModalMode(null)}
        />
      )}
    </div>
  );
}
