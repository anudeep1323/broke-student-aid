import { useEffect, useState } from "react";
import { getProducts } from "./api";
import type { Product } from "./types";

const STAPLES = ["🍚 rice", "🥚 eggs", "🫘 black beans", "🟤 lentils", "🍝 pasta", "🥔 potatoes", "🧅 onions", "🥛 milk", "🍞 bread", "🥜 peanut butter"];
const money = (n: number) => `$${n.toFixed(2)}`;
const term = (s: string) => s.replace(/^\S+ /, "");

/** Browse Kroger without asking anything: one group per food, best value first, the rest one click away. Code only, $0. */
export function Browse({ locationId, budget }: { locationId: string; budget: number }) {
  const [picked, setPicked] = useState<string[]>([]);
  const [typed, setTyped] = useState("");
  const [basket, setBasket] = useState<Record<string, Product>>({});
  const wanted = [...new Set([...picked.map(term), ...typed.split(",").map((s) => s.trim()).filter((s) => s.length > 1)])];
  const total = Object.values(basket).reduce((s, p) => s + p.best, 0);

  const toggle = (p: Product) =>
    setBasket((b) => {
      const n = { ...b };
      if (n[p.product_id]) delete n[p.product_id];
      else n[p.product_id] = p;
      return n;
    });

  return (
    <div>
      <div className="pills">
        {STAPLES.map((s) => (
          <button key={s} className={picked.includes(s) ? "pill on" : "pill"}
                  onClick={() => setPicked((p) => (p.includes(s) ? p.filter((x) => x !== s) : [...p, s]))}>{s}</button>
        ))}
      </div>
      <input className="search" placeholder="Or type anything, e.g. tofu, frozen spinach (comma-separated, then Enter)"
             onKeyDown={(e) => e.key === "Enter" && setTyped((e.target as HTMLInputElement).value)} />
      {wanted.length === 0 && <p className="muted">👆 Pick a staple or type a food to see real prices at your Kroger.</p>}
      {wanted.map((t) => <FoodGroup key={t} term={t} locationId={locationId} basket={basket} toggle={toggle} />)}

      <div className="basket">
        <b>🧺 Basket: {Object.keys(basket).length} items · {money(total)} of {money(budget)}</b>
        <div className="bar"><div style={{ width: `${Math.min(100, (total / budget) * 100)}%` }} className={total > budget ? "over" : ""} /></div>
        <span className={total > budget ? "bad" : "good"}>{total > budget ? `${money(total - budget)} over budget` : `${money(budget - total)} left`}</span>
      </div>
    </div>
  );
}

function FoodGroup({ term, locationId, basket, toggle }:
  { term: string; locationId: string; basket: Record<string, Product>; toggle: (p: Product) => void }) {
  const [rows, setRows] = useState<Product[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getProducts(locationId, term).then(setRows).catch((e) => setError(String(e.message ?? e)));
  }, [locationId, term]);

  if (error) return <div className="group"><b>{term}</b> <span className="error">{error}</span></div>;
  if (!rows) return <div className="group muted">Loading {term}…</div>;
  if (rows.length === 0) return <div className="group muted">No products found for “{term}”.</div>;
  const row = (p: Product) => (
    <label key={p.product_id} className="product">
      <input type="checkbox" checked={!!basket[p.product_id]} onChange={() => toggle(p)} />
      <b>{money(p.best)}</b> · {p.name} · {p.size} · {p.unit_price != null ? `${money(p.unit_price)}/${p.unit}` : "size?"}
      {p.promo && <span className="sale"> sale (reg {money(p.regular)})</span>}
    </label>
  );
  return (
    <div className="group">
      <div><b>{term[0].toUpperCase() + term.slice(1)}</b> <span className="muted">· {rows.length} options · from {money(Math.min(...rows.map((r) => r.best)))}</span></div>
      <div className="muted small">⭐ Best value (cheapest per unit)</div>
      {row(rows[0])}
      {rows.length > 1 && (
        <details>
          <summary>See {rows.length - 1} more sizes and brands</summary>
          {rows.slice(1).map(row)}
        </details>
      )}
    </div>
  );
}
