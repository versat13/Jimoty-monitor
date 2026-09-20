import { useState, useEffect } from "react";

/**
 * 画面幅がbreakpoint以上かどうかを返すフック。
 *
 * 2026-08-26: テーブルモードの列幅調整で、PCではドラッグリサイズ
 * (Excel等でおなじみの操作)、スマホでは横スクロール＋自動幅
 * (誤操作を招きやすいドラッグ操作を避ける) と挙動を分けるために導入した。
 */
export function useIsDesktop(breakpoint = 768) {
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= breakpoint
  );

  useEffect(() => {
    const onResize = () => setIsDesktop(window.innerWidth >= breakpoint);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);

  return isDesktop;
}
