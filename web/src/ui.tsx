import { useEffect, useRef, useState } from "react";

/** Animate a number from 0 up to `to` when it first appears (or changes). Respects reduced-motion settings. */
export function useCountUp(to: number, ms = 900) {
  const [v, setV] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setV(to);
      return;
    }
    const start = performance.now(), a = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms), ease = 1 - Math.pow(1 - t, 3);
      setV(a + (to - a) * ease);
      if (t < 1) raf = requestAnimationFrame(tick);
      else from.current = to;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, ms]);
  return v;
}

/** A progress ring: `value` of `max`, filled in `color`, with the big number in the middle. */
export function Ring({ value, max, color, label, center, sub }:
  { value: number; max: number; color: string; label: string; center: string; sub?: string }) {
  const R = 46, C = 2 * Math.PI * R;
  const share = useCountUp(max > 0 ? Math.min(1, value / max) : 0);
  return (
    <div className="ring">
      <svg viewBox="0 0 110 110" role="img" aria-label={`${label}: ${center}`}>
        <circle cx="55" cy="55" r={R} className="ring-track" />
        <circle cx="55" cy="55" r={R} className="ring-fill" stroke={color}
                strokeDasharray={C} strokeDashoffset={C * (1 - share)} />
      </svg>
      <div className="ring-center">
        <b>{center}</b>
        <span>{label}</span>
      </div>
      {sub && <div className="ring-sub">{sub}</div>}
    </div>
  );
}

/** Count-up money / numbers for the headline figures. */
export function Num({ value, money, decimals = 0 }: { value: number; money?: boolean; decimals?: number }) {
  const v = useCountUp(value);
  return <>{money ? `$${v.toFixed(2)}` : v.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}</>;
}

// One colour per recipe, used on its card, its calendar chips and its shopping lines
export const RECIPE_COLORS = ["#E4572E", "#5B8C3A", "#F2A93B", "#8E4A6D", "#2E7D8C"];
