import { useEffect, useState } from "react";
import { getRecipe } from "./api";
import type { FullRecipe } from "./types";

/** Full recipe over the page: photo, nutrition, ingredients, steps. Read from the saved card: no AI call, $0. */
export function RecipeModal({ title, page, onClose }: { title: string; page: number; onClose: () => void }) {
  const [r, setR] = useState<FullRecipe | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getRecipe(title, page).then(setR).catch((e) => setError(String(e.message ?? e)));
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [title, page, onClose]);

  const n = r?.nutrition;
  const per = n?.per_serving ?? n?.whole_recipe;
  const label = n?.per_serving ? `per ${n.per} (makes ${n.servings} ${n.per}s)` : "whole recipe (servings unknown)";

  return (
    <div className="overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        <h2>{title} <span className="muted">· Good and Cheap p.{page}</span></h2>
        {error && <p className="error">{error}</p>}
        {!r && !error && <p className="muted">Loading…</p>}
        {r && (
          <>
            <div className="modal-top">
              {r.photo_id && <img src={`/images/${r.photo_id}.png`} alt={r.title} />}
              {per && (
                <div>
                  <p className="muted small">Nutrition {label}, from USDA data</p>
                  <div className="nutri">
                    <Stat v={per.calories} l="kcal" /> <Stat v={per.protein_g} l="protein g" /> <Stat v={per.carbs_g} l="carbs g" />
                    <Stat v={per.fiber_g} l="fiber g" /> <Stat v={per.sugar_g} l="sugar g" />
                  </div>
                </div>
              )}
            </div>
            <div className="modal-body">
              <div>
                <h3>Ingredients {r.makes && <span className="muted">({r.makes})</span>}</h3>
                {r.ingredient_groups.map((g, i) => (
                  <div key={i}>
                    {g.name && <em>{g.name}</em>}
                    <ul>{g.items.map((it) => <li key={it}>{it}</li>)}</ul>
                  </div>
                ))}
              </div>
              <div>
                <h3>How to make it</h3>
                <p className="method">{r.steps}</p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const Stat = ({ v, l }: { v: number; l: string }) => (
  <div className="stat"><b>{v}</b><span>{l}</span></div>
);
