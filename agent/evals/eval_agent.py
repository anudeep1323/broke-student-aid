"""Agent eval: 12 student sentences through agent/graph.py, every answer checked by code (no LLM judge).

Checks read the submitted JSON plan (no regex over prose): 1 within budget, 2 plan complete (recipes, items, line math),
3 note has no made-up numbers ($ only from tools, no nutrition numbers), 4 recipes respect avoid/vegetarian,
5 every recipe was shown by the recipe tools.
Measured, not pass/fail: kcal and protein eaten per day, servings planned, rejected plans (retries), protein goal met.
Usage: python3 -I agent/evals/eval_agent.py [label]      (~$0.06 per case, ~40 s, 2 at a time)
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from graph import PRICES, app, final_plan   # noqa: E402
from tools import cards, kroger_headers   # noqa: E402
from browse import nearest_store   # noqa: E402

LOCATION, _ = nearest_store(kroger_headers(), "45202")
CASES = [  # (sentence, weekly budget, allergens to avoid, vegetarian, protein goal g/day; 0 = slider off)
    ("I'm broke till Friday, no peanuts, tired of rice, want something warm", 25, {"peanut"}, False, 0),
    ("vegetarian, $20 for the week, I like spicy food", 20, set(), True, 0),
    ("dairy-free, cheap breakfasts and dinners", 30, {"milk"}, False, 0),
    ("I have a nut allergy, need lunches I can carry to class", 25, {"peanut", "tree_nut"}, False, 0),
    ("gluten free please, something filling", 30, {"wheat"}, False, 0),
    ("cheapest possible week of dinners, I eat anything", 15, set(), False, 0),
    ("I can't eat shellfish or eggs, want some comfort food", 25, {"shellfish", "egg"}, False, 0),
    ("I want to meal prep on Sunday for the whole week", 35, set(), False, 0),
    ("vegetarian, no soy, I need protein", 25, {"soy"}, True, 0),
    ("sweet breakfast ideas, I hate oatmeal", 20, set(), False, 0),
    # protein slider cases (added 2026-11-20; the first 10 stay as they were, so old runs compare)
    ("cheap high protein dinners, I lift weights", 30, set(), False, 100),
    ("vegetarian and I want lots of protein", 25, set(), True, 80),
]
NAMES = ["1 within budget", "2 plan complete", "3 no made-up numbers", "4 diet respected", "5 pages real"]
NUTRIENT_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:g\b|grams|kcal|calories)", re.I)   # "24 g", "381 kcal"
MONEY = re.compile(r"\$(\d+(?:\.\d{1,2})?)")
norm = lambda t: re.sub(r"[^a-z0-9 ]", "", t.lower().replace("’", "'").replace("'", ""))


def cost_of(out):
    """$ for every Claude call in one run (cache reads priced separately)."""
    total = 0
    for m in out["messages"] + out["plan_messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            p_in, p_out, p_read = next(v for k, v in PRICES.items() if m.response_metadata.get("model_name", "").startswith(k))
            read = (u.get("input_token_details", {}) or {}).get("cache_read", 0) or 0
            total += ((u["input_tokens"] - read) * p_in + read * p_read + u["output_tokens"] * p_out) / 1e6
    return total


def check(case, out):
    """Run the 5 code checks on the submitted JSON plan; returns {check: (passed, why)}. No regex over prose."""
    sentence, budget, avoid, veg, goal = case
    plan = final_plan(out)
    if plan is None:
        return {n: (False, "no accepted plan") for n in NAMES}
    tool_msgs = [m for m in out["messages"] + out["plan_messages"] if isinstance(m, ToolMessage)]
    shown = {(c["title"], c["page"]) for m in tool_msgs if m.name in ("find_recipes", "recipe_details")
             for c in (json.loads(m.content) if m.content.startswith("[") else [json.loads(m.content)]) if "title" in c}
    tool_text = " ".join(m.content for m in tool_msgs if m.name != "submit_plan")
    known = {float(x) for x in re.findall(r'"(?:price|line_total|total|left|budget)":\s*(-?\d+(?:\.\d+)?)', tool_text)}
    said = [float(x) for x in MONEY.findall(plan["note"])]
    recs = plan["recipes"]
    bad = [r["title"] for r in recs if set(r["allergens"]) & avoid or (veg and r["vegetarian"] == "no")]
    lines_ok = all(l["line_total"] == round(l["price"] * l["quantity"], 2) for l in plan["lines"])
    return {
        "1 within budget": (plan["total"] <= budget, f"total {plan['total']} of ${budget}"),
        "2 plan complete": (bool(recs) and bool(plan["lines"]) and lines_ok and not plan.get("unknown_ids"),
                            f"{len(recs)} recipes, {len(plan['lines'])} items, line math ok {lines_ok}"),
        "3 no made-up numbers": (all(abs(x) in known for x in said) and not NUTRIENT_NUMBER.search(plan["note"]),
                                 f"note $: {said}, nutrient numbers: {NUTRIENT_NUMBER.findall(plan['note'])}"),
        "4 diet respected": (not bad, f"recipes {[r['title'] for r in recs]}, violations {bad}"),
        "5 pages real": (all((r["title"], r["page"]) in shown for r in recs),
                         f"plan {[(r['title'], r['page']) for r in recs]} not all shown by tools"),
    }


def measure(out, plan):
    """Numbers we track but don't pass/fail on: week coverage, retries, protein goal."""
    rejected = sum(1 for m in out["plan_messages"] if isinstance(m, ToolMessage) and m.name == "submit_plan"
                   and not json.loads(m.content).get("accepted"))
    if plan is None:
        return {"rejected": rejected}
    return {"kcal_day": plan["eaten_per_day"]["calories"], "protein_day": plan["eaten_per_day"]["protein_g"],
            "servings": plan["servings_planned"], "rejected": rejected, "goal_met": plan.get("goal_met"),
            "meals": f"{plan['meals_planned']}/{plan['meals_target']}", "week_covered": plan["meals_planned"] >= plan["meals_target"],
            "budget_limited": plan["budget_limited"]}


def run(case):
    """One case through the agent: (case, checks, $, seconds, plan, measures). A crash = every check failed."""
    t0 = time.time()
    try:
        out = app.invoke({"messages": [HumanMessage(case[0])], "plan_messages": [], "location_id": LOCATION,
                          "budget": float(case[1]), "tool_calls": [], "protein_goal": case[4]})
    except Exception as e:  # noqa: BLE001
        return case, {n: (False, f"CRASHED: {type(e).__name__}: {str(e)[:80]}") for n in NAMES}, 0.0, time.time() - t0, None, {}
    plan = final_plan(out)
    return case, check(case, out), cost_of(out), time.time() - t0, plan, measure(out, plan)


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "current"
    with ThreadPoolExecutor(max_workers=2) as pool:   # 3 at once hit Kroger's rate limit
        results = list(pool.map(run, CASES))
    for case, r, cost, secs, plan, m in results:
        fails = [f"{k} ({why})" for k, (ok, why) in r.items() if not ok]
        week = (f"meals {m['meals']:>5} {m['kcal_day']:>5} kcal/day {m['protein_day']:>3} g protein/day"
                + (f" goal {case[4]} {'met' if m['goal_met'] else 'MISSED'}" if case[4] else "")) if "kcal_day" in m else "no plan"
        print(f"{'PASS' if not fails else 'FAIL'} ${cost:.3f} {secs:4.0f}s  {case[0][:40]:40} | {week} | rejected {m.get('rejected', '?')}")
        for f in fails:
            print("       x", f)
    print(f"\n[{label}] " + " | ".join(f"{n}: {sum(r[n][0] for _, r, *_ in results)}/{len(results)}" for n in NAMES))
    costs = [c for _, _, c, *_ in results]
    ms = [m for *_, m in results if "kcal_day" in m]
    goals = [m["goal_met"] for (c, *_), m in zip(results, [x[-1] for x in results]) if c[4] and "kcal_day" in m]
    print(f"[{label}] all 5 checks: {sum(all(ok for ok, _ in r.values()) for _, r, *_ in results)}/{len(results)} | "
          f"${sum(costs) / len(costs):.4f} per answer, ${sum(costs):.3f} total")
    print(f"[{label}] week coverage: median {sorted(m['kcal_day'] for m in ms)[len(ms) // 2]} kcal/day "
          f"(range {min(m['kcal_day'] for m in ms)}-{max(m['kcal_day'] for m in ms)}), "
          f"week covered {sum(m['week_covered'] for m in ms)}/{len(ms)} (budget ran out: {sum(m['budget_limited'] for m in ms)}) | rejected plans: {sum(m.get('rejected', 0) for *_, m in results)} "
          f"| protein goal met: {sum(bool(g) for g in goals)}/{len(goals)}")
    json.dump([{"case": c[0], "plan": p, "checks": {k: v[0] for k, v in r.items()}, "cost": cost, "measures": m}
               for c, r, cost, _, p, m in results], open(HERE / f"results_{label}.json", "w"), indent=1)
