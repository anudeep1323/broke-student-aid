import type { Step } from "./types";

// The agent's tool calls, grouped into the 5 stages a student understands
const STAGES = [
  { key: "read", icon: "💬", title: "Reading your request", tools: [] as string[] },
  { key: "cook", icon: "📖", title: "Searching the cookbook", tools: ["find_recipes", "recipe_details"] },
  { key: "shop", icon: "🛒", title: "Checking prices at your Kroger", tools: ["search_kroger"] },
  { key: "plan", icon: "🧮", title: "Pricing shopping lists", tools: ["check_budget"] },
  { key: "check", icon: "✅", title: "Checking budget, allergens & the whole week", tools: ["submit_plan"] },
];

/** Animated timeline: done stages get a tick, the current one pulses, later ones wait. Collapses to one line when done. */
export function Timeline({ steps, running, failed, seconds, cost }:
  { steps: Step[]; running: boolean; failed?: boolean; seconds?: number; cost?: number }) {
  const reached = (i: number) => STAGES[i].tools.length === 0 || steps.some((s) => STAGES[i].tools.includes(s.tool));
  let last = 0;
  STAGES.forEach((_, i) => { if (reached(i)) last = i; });
  const count = (i: number) => steps.filter((s) => STAGES[i].tools.includes(s.tool)).length;

  if (!running && !failed) {
    return (
      <div className="timeline-done">
        <span className="tick">✓</span> Planned in {seconds ?? "–"} s · {steps.length} steps by the agent
        {cost != null && <> · ${cost.toFixed(3)}</>}
      </div>
    );
  }
  return (
    <ol className="timeline" aria-live="polite">
      {STAGES.map((s, i) => {
        const state = i < last || (!running && reached(i)) ? "done" : i === last && running ? "active" : failed && i === last ? "failed" : "todo";
        const n = count(i);
        return (
          <li key={s.key} className={`tl ${state}`}>
            <span className="tl-dot">{state === "done" ? "✓" : state === "failed" ? "!" : s.icon}</span>
            <span className="tl-text">
              {s.title}
              {n > 1 && <span className="tl-count">×{n}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
