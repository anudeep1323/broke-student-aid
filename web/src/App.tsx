import { useEffect, useRef, useState } from "react";
import { getStore, streamPlan } from "./api";
import { Browse } from "./Browse";
import { PlanView } from "./PlanView";
import { Timeline } from "./Timeline";
import type { Plan, Step } from "./types";

type Turn = { question: string; steps: Step[]; plan?: Plan; error?: string; running: boolean };

const EXAMPLES = [
  "I'm broke till Friday, no peanuts, tired of rice, want something warm",
  "vegetarian, cheap dinners for the week, I lift weights",
  "dairy-free breakfasts and dinners",
  "lunches I can carry to class, nut allergy",
];

export default function App() {
  const [zip, setZip] = useState("");
  const [budget, setBudget] = useState(25);
  const [goal, setGoal] = useState(0);
  const [store, setStore] = useState<{ location_id: string; name: string } | null>(null);
  const [storeError, setStoreError] = useState("");
  const [tab, setTab] = useState<"ask" | "browse">("ask");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sentence, setSentence] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const zipInput = useRef<HTMLInputElement>(null);
  const running = turns.some((t) => t.running);

  useEffect(() => {   // ZIP -> nearest Kroger, once 5 digits are typed
    setStore(null);
    setStoreError("");
    if (/^\d{5}$/.test(zip)) getStore(zip).then(setStore).catch((e) => setStoreError(e.message));
  }, [zip]);

  useEffect(() => {   // braces: return nothing (scrollIntoView returns a Promise in new browsers)
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  const update = (i: number, f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t, j) => (j === i ? f(t) : t)));

  async function ask(text = sentence) {
    if (!store) { zipInput.current?.focus(); return; }
    if (text.trim().length < 3 || running) return;
    const i = turns.length;
    setTurns((ts) => [...ts, { question: text, steps: [], running: true }]);
    setSentence("");
    await streamPlan({ sentence: text, zip, budget, protein_goal: goal }, {
      onStep: (s) => update(i, (t) => ({ ...t, steps: [...t.steps, s] })),
      onPlan: (p) => update(i, (t) => ({ ...t, plan: p })),
      onError: (m) => update(i, (t) => ({ ...t, error: m })),
    }).catch((e) => update(i, (t) => ({ ...t, error: String(e) })));
    update(i, (t) => ({ ...t, running: false }));
  }

  return (
    <div className="app">
      <header>
        <div className="brand"><span className="logo">🥑</span><div><b>Broke Student Aid</b><small>a week of meals on a student budget</small></div></div>
        <div className="controls">
          <label className={`field ${store ? "ok" : ""}`}>
            <span>📍 ZIP</span>
            <input ref={zipInput} value={zip} maxLength={5} inputMode="numeric" placeholder="45202"
                   onChange={(e) => setZip(e.target.value.replace(/\D/g, ""))} />
          </label>
          <label className="field">
            <span>💵 Budget</span>
            <div className="stepper">
              <button type="button" onClick={() => setBudget((b) => Math.max(5, b - 5))} aria-label="Less">−</button>
              <b>${budget}</b>
              <button type="button" onClick={() => setBudget((b) => Math.min(200, b + 5))} aria-label="More">+</button>
            </div>
          </label>
          <label className="field protein">
            <span>💪 Protein goal <b>{goal ? `${goal} g/day` : "off"}</b></span>
            <input type="range" min={0} max={150} step={10} value={goal} onChange={(e) => setGoal(Number(e.target.value))} />
          </label>
        </div>
        <div className="store-line">
          {store ? <span className="good">✓ {store.name}</span>
            : storeError ? <span className="bad">{storeError}</span>
            : <span className="muted">Enter your ZIP to use your nearest Kroger's prices</span>}
        </div>
      </header>

      <main>
        <nav className="tabs">
          <button className={tab === "ask" ? "on" : ""} onClick={() => setTab("ask")}>✨ Plan my week</button>
          <button className={tab === "browse" ? "on" : ""} onClick={() => setTab("browse")}>🔎 Browse Kroger</button>
        </nav>

        {tab === "browse" && (store ? <Browse locationId={store.location_id} budget={budget} />
          : <div className="empty"><p>📍 Enter your ZIP above to browse your Kroger.</p></div>)}

        {tab === "ask" && (
          <>
            {turns.length === 0 && (
              <div className="welcome">
                <h1>What do you feel like eating this week?</h1>
                <p className="muted">Say it in your own words. I'll pick recipes from <i>Good and Cheap</i>, price them at your Kroger,
                  and check the budget, your allergies and that you're fed all week.</p>
                <div className="examples">
                  {EXAMPLES.map((e) => <button key={e} onClick={() => ask(e)} disabled={running}>{e}</button>)}
                </div>
                {!store && <p className="hint">👆 Start with your ZIP code</p>}
              </div>
            )}
            {turns.map((t, i) => (
              <section key={i} className="turn">
                <div className="you">{t.question}</div>
                <Timeline steps={t.steps} running={t.running} failed={!!t.error} seconds={t.plan?.seconds} cost={t.plan?.cost} />
                {t.error && <p className="error">{t.error}</p>}
                {t.plan && <PlanView plan={t.plan} />}
              </section>
            ))}
            <div ref={bottom} />
            <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(); }}>
              <input value={sentence} onChange={(e) => setSentence(e.target.value)}
                     placeholder={store ? "Tell me what you need, e.g. vegetarian, cheap dinners, I lift weights" : "Enter your ZIP first"} />
              <button disabled={running || sentence.trim().length < 3}>{running ? "Planning…" : "Plan my week"}</button>
            </form>
          </>
        )}
      </main>
      <footer className="muted">Recipes and photos: <i>Good and Cheap</i> by Leanne Brown (CC BY-NC-SA). Prices: Kroger. Nutrition: USDA.</footer>
    </div>
  );
}
