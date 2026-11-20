"""Agent eval: 10 student sentences through agent/graph.py, every answer checked by code (no LLM judge).

Checks read the submitted JSON plan (no regex over prose): 1 within budget, 2 plan complete (recipes, items, line math),
3 every $ in the note came from a tool, 4 recipes respect avoid/vegetarian, 5 every recipe was shown by the recipe tools.
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
CASES = [  # (sentence, weekly budget, allergens to avoid, vegetarian)
    ("I'm broke till Friday, no peanuts, tired of rice, want something warm", 25, {"peanut"}, False),
    ("vegetarian, $20 for the week, I like spicy food", 20, set(), True),
    ("dairy-free, cheap breakfasts and dinners", 30, {"milk"}, False),
    ("I have a nut allergy, need lunches I can carry to class", 25, {"peanut", "tree_nut"}, False),
    ("gluten free please, something filling", 30, {"wheat"}, False),
    ("cheapest possible week of dinners, I eat anything", 15, set(), False),
    ("I can't eat shellfish or eggs, want some comfort food", 25, {"shellfish", "egg"}, False),
    ("I want to meal prep on Sunday for the whole week", 35, set(), False),
    ("vegetarian, no soy, I need protein", 25, {"soy"}, True),
    ("sweet breakfast ideas, I hate oatmeal", 20, set(), False),
]
NAMES = ["1 within budget", "2 plan complete", "3 every $ from a tool", "4 diet respected", "5 pages real"]
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
    sentence, budget, avoid, veg = case
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
        "3 every $ from a tool": (all(abs(x) in known for x in said), f"note $: {said}"),
        "4 diet respected": (not bad, f"recipes {[r['title'] for r in recs]}, violations {bad}"),
        "5 pages real": (all((r["title"], r["page"]) in shown for r in recs),
                         f"plan {[(r['title'], r['page']) for r in recs]} not all shown by tools"),
    }


def run(case):
    """One case through the agent: (case, checks, $, seconds). A crash = every check failed, the other cases go on."""
    t0 = time.time()
    try:
        out = app.invoke({"messages": [HumanMessage(case[0])], "plan_messages": [], "location_id": LOCATION,
                          "budget": float(case[1]), "tool_calls": []})
    except Exception as e:  # noqa: BLE001
        return case, {n: (False, f"CRASHED: {type(e).__name__}: {str(e)[:80]}") for n in NAMES}, 0.0, time.time() - t0, None
    return case, check(case, out), cost_of(out), time.time() - t0, final_plan(out)


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "current"
    with ThreadPoolExecutor(max_workers=2) as pool:   # 3 at once hit Kroger's rate limit
        results = list(pool.map(run, CASES))
    names = list(results[0][1])
    for case, r, cost, secs, answer in results:
        fails = [f"{k} ({why})" for k, (ok, why) in r.items() if not ok]
        print(f"{'PASS' if not fails else 'FAIL'} ${cost:.3f} {secs:4.0f}s  {case[0][:50]}")
        for f in fails:
            print("       x", f)
    print(f"\n[{label}] " + " | ".join(f"{n}: {sum(r[n][0] for _, r, *_ in results)}/{len(results)}" for n in names))
    costs = [c for _, _, c, _, _ in results]
    print(f"[{label}] all 5 checks: {sum(all(ok for ok, _ in r.values()) for _, r, *_ in results)}/{len(results)} | "
          f"${sum(costs) / len(costs):.4f} per answer, ${sum(costs):.3f} total")
    json.dump([{"case": c[0], "plan": a, "checks": {k: v[0] for k, v in r.items()}, "cost": cost}
               for c, r, cost, _, a in results], open(HERE / f"results_{label}.json", "w"), indent=1)
