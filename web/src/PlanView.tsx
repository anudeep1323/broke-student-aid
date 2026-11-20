import { useEffect, useMemo, useState } from "react";
import { RecipeModal } from "./RecipeModal";
import type { Plan } from "./types";
import { Num, RECIPE_COLORS, Ring } from "./ui";

const money = (n: number) => `$${n.toFixed(2)}`;

/** One checked plan. Every number comes from the plan JSON (code); only the note is the model's words. */
export function PlanView({ plan }: { plan: Plan }) {
  const [open, setOpen] = useState<{ title: string; page: number } | null>(null);
  const day = plan.eaten_per_day;
  const goal = plan.protein_goal_g_per_day;
  const days = Object.keys(plan.calendar);
  const color = useMemo(() => Object.fromEntries(plan.recipes.map((r, i) => [r.title, RECIPE_COLORS[i % RECIPE_COLORS.length]])),
                        [plan.recipes]);

  return (
    <div className="plan">
      <div className="hero">
        <div>
          <p className="eyebrow">Your week</p>
          <h2><Num value={plan.total} money /> <span className="of">of {money(plan.budget)}</span></h2>
          <p className="muted">{money(plan.left)} left · {plan.lines.length} items at Kroger · {plan.recipes.length} recipes</p>
        </div>
        <div className="rings">
          <Ring value={plan.total} max={plan.budget} color="var(--tomato)" label="of budget"
                center={`${Math.round((plan.total / plan.budget) * 100)}%`} />
          <Ring value={plan.meals_planned} max={plan.meals_target} color="var(--avocado)" label="meals"
                center={`${plan.meals_planned}/${plan.meals_target}`}
                sub={plan.budget_limited ? "budget ran out" : plan.meals.join(" + ")} />
          <Ring value={day.protein_g} max={goal || 60} color="var(--saffron)" label="protein / day"
                center={`${day.protein_g} g`} sub={goal ? (plan.goal_met ? `goal ${goal} g ✓` : `${plan.protein_short_g_per_day} g short of ${goal}`) : "no goal set"} />
        </div>
      </div>

      <div className="note"><span className="note-icon">🧑‍🍳</span><p>{plan.note}</p></div>

      <div className="macros">
        <span><b><Num value={day.calories} /></b> kcal/day</span>
        <span><b><Num value={day.carbs_g} /> g</b> carbs</span>
        <span><b><Num value={day.fiber_g} /> g</b> fiber</span>
        <span><b><Num value={day.sugar_g} /> g</b> sugar</span>
        <span className="muted small">eaten, from the recipes × batches</span>
      </div>

      <h3>🗓️ Mon–Sun</h3>
      <div className="week">
        {days.map((d) => (
          <div key={d} className="day">
            <div className="day-name">{d}</div>
            {plan.meals.map((m) => {
              const dish = plan.calendar[d][m];
              return (
                <button key={m} className={`chip ${dish ? "" : "gap"}`} disabled={!dish}
                        style={dish ? { "--c": color[dish] } as React.CSSProperties : undefined}
                        onClick={() => { const r = plan.recipes.find((x) => x.title === dish); if (r) setOpen({ title: r.title, page: r.page }); }}
                        title={dish ? `${m}: ${dish}` : `${m}: not covered`}>
                  <small>{m}</small>{dish ?? "–"}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      <h3>🍳 What you'll cook</h3>
      <div className="cards">
        {plan.recipes.map((r) => {
          const per = r.nutrition?.per_serving;
          return (
            <button key={`${r.title}${r.page}`} className="card" style={{ "--c": color[r.title] } as React.CSSProperties}
                    onClick={() => setOpen({ title: r.title, page: r.page })}>
              <div className="card-photo">
                {r.photo_id ? <img src={`/images/${r.photo_id}.png`} alt="" loading="lazy" /> : <div className="nophoto">🍲</div>}
                <span className="badge">cook ×{r.batches}</span>
                <div className="card-title"><b>{r.title}</b><span>Good and Cheap · p.{r.page}</span></div>
              </div>
              <div className="card-body">
                {per ? (
                  <div className="card-stats">
                    <span><b>{per.protein_g} g</b> protein</span><span><b>{per.calories}</b> kcal</span>
                    <span className="muted">per {r.nutrition?.per}</span>
                  </div>
                ) : <span className="muted small">nutrition for the whole recipe</span>}
                <span className="link">See the recipe →</span>
              </div>
            </button>
          );
        })}
      </div>

      <ShoppingList plan={plan} />

      <details className="json">
        <summary>🧩 The plan as JSON (what code checked)</summary>
        <pre>{JSON.stringify(plan, null, 1)}</pre>
      </details>

      {open && <RecipeModal title={open.title} page={open.page} onClose={() => setOpen(null)} />}
    </div>
  );
}

/** Tick items off in the store. Remembered on this device (browser storage), per plan. */
function ShoppingList({ plan }: { plan: Plan }) {
  const key = "basket:" + plan.lines.map((l) => `${l.id}x${l.quantity}`).join(",");
  const [got, setGot] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem(key) ?? "{}"); } catch { return {}; }
  });
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(got)); } catch { /* private mode: still works, just not remembered */ } },
            [key, got]);
  const spent = plan.lines.filter((l) => got[l.id]).reduce((s, l) => s + l.line_total, 0);
  const n = plan.lines.filter((l) => got[l.id]).length;

  return (
    <div className="shop">
      <div className="shop-head">
        <h3>🧾 Shopping list</h3>
        <span className={n === plan.lines.length ? "good" : "muted"}>
          {n === plan.lines.length ? "All in the cart 🎉" : `${n} of ${plan.lines.length} in the cart · ${money(spent)} of ${money(plan.total)}`}
        </span>
      </div>
      <div className="bar"><div style={{ width: `${(spent / plan.total) * 100}%` }} /></div>
      <ul className="lines">
        {plan.lines.map((l) => (
          <li key={l.id} className={got[l.id] ? "got" : ""}>
            <label>
              <input type="checkbox" checked={!!got[l.id]} onChange={() => setGot((g) => ({ ...g, [l.id]: !g[l.id] }))} />
              <span className="box" aria-hidden>✓</span>
              <span className="line-name">{l.name}<small>{l.size}{l.protein_g != null && ` · ${l.protein_g} g protein`}</small></span>
              <span className="line-price">
                {l.quantity > 1 && <small>{money(l.price)} × {l.quantity}</small>}
                <b>{money(l.line_total)}</b>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <p className="muted small">
        Total {money(plan.total)}. Groceries hold {plan.protein_g_per_day} g protein/day by Kroger labels (leftovers included);
        the rings count what the recipes use.{plan.no_label.length > 0 && ` No label: ${plan.no_label.join(", ")}.`}
      </p>
    </div>
  );
}
