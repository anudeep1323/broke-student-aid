"""Agent eval: 10 student sentences through agent/graph.py, every answer checked by code (no LLM judge).

Checks: 1 within budget, 2 answer total = check_budget total and every priced item is listed,
3 every $ in the answer came from a tool, 4 recipes respect avoid/vegetarian, 5 cited pages are real.
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
from graph import PRICES, app   # noqa: E402
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
    """Run the 5 code checks on one answer; returns {check: (passed, why)}."""
    sentence, budget, avoid, veg = case
    answer = out["plan_messages"][-1].text
    tool_msgs = [m for m in out["messages"] + out["plan_messages"] if isinstance(m, ToolMessage)]
    budgets = [json.loads(m.content) for m in tool_msgs if m.name == "check_budget"]
    last = budgets[-1] if budgets else None
    picked = [m for m in out["plan_messages"] if getattr(m, "tool_calls", None)]
    prices = picked[-1].tool_calls[-1]["args"]["prices"] if picked else []
    said = [float(x) for x in MONEY.findall(answer)]
    tool_text = " ".join(m.content for m in tool_msgs)
    tool_numbers = re.findall(r'"(?:price|total|left|budget)":\s*(-?\d+(?:\.\d+)?)', tool_text)
    known = ({float(x) for x in MONEY.findall(tool_text)} | {float(budget)}
             | {abs(float(x)) for x in tool_numbers})   # abs: "left": -1.38 is said as "$1.38 over"
    shown = {c["title"] for m in tool_msgs if m.name in ("find_recipes", "recipe_details")
             for c in (json.loads(m.content) if m.content.startswith("[") else [json.loads(m.content)]) if "title" in c}
    recs = [c for c in cards if c["title"] in shown and norm(c["title"]) in norm(answer)]
    r = {}
    r["1 within budget"] = (bool(last) and last["within_budget"], f"total {last and last['total']} of ${budget}")
    r["2 total + items match"] = (bool(last) and last["total"] in said and all(p in said for p in prices),
                                  f"missing from answer: {[p for p in prices if p not in said]}")
    r["3 every $ from a tool"] = (all(x in known for x in said), f"made up: {sorted(set(x for x in said if x not in known))}")
    bad = [c["title"] for c in recs if c["allergens"] & avoid or (veg and c["vegetarian"] == "no")]
    r["4 diet respected"] = (bool(recs) and not bad, f"recipes {[c['title'] for c in recs]}, violations {bad}")
    pages = {int(p) for p in re.findall(r"p(?:age|\.)?\s*(\d{1,3})", answer)}
    real = {c["book_page"] for c in recs}
    r["5 pages real"] = (pages <= real | {c["book_page"] for c in cards if c["title"] in shown}, f"cited {sorted(pages)}, real {sorted(real)}")
    return r


def run(case):
    """One case through the agent: (case, checks, $, seconds). A crash = every check failed, the other cases go on."""
    t0 = time.time()
    try:
        out = app.invoke({"messages": [HumanMessage(case[0])], "plan_messages": [], "location_id": LOCATION,
                          "budget": float(case[1]), "tool_calls": []})
    except Exception as e:  # noqa: BLE001
        names = ["1 within budget", "2 total + items match", "3 every $ from a tool", "4 diet respected", "5 pages real"]
        return case, {n: (False, f"CRASHED: {type(e).__name__}: {str(e)[:80]}") for n in names}, 0.0, time.time() - t0, ""
    return case, check(case, out), cost_of(out), time.time() - t0, out["plan_messages"][-1].text


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
    json.dump([{"case": c[0], "answer": a, "checks": {k: v[0] for k, v in r.items()}, "cost": cost}
               for c, r, cost, _, a in results], open(HERE / f"results_{label}.json", "w"), indent=1)
