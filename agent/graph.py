"""Agent piece 4: Haiku 5.5 gathers facts (fetching jobs), Opus 5.5 decides and writes (judgment jobs).

gatherer (Haiku) <-> gather tools ... --DONE--> planner (Opus) <-> check_budget ... --> answer --> END
Usage: python3 -I agent/graph.py 45202 25 "I'm broke till Friday, no peanuts, tired of rice, want something warm" [protein_goal_g_per_day]
"""
import json
import operator
import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools import check_budget, find_recipes, kroger_headers, recipe_details, search_kroger, submit_plan   # noqa: E402

GATHER_MODEL = "claude-haiku-5-5"
PLAN_MODEL = os.environ.get("PLAN_MODEL", "claude-sonnet-5-5")   # M7: Sonnet passed 10/10 at half of Opus cost
PRICES = {  # $ per million tokens: input, output, cache read
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    GATHER_MODEL: (0.10, 0.50, 0.01),
}
CACHE = {"type": "ephemeral"}   # top-level auto-caching: repeat calls re-read earlier turns from cache
GATHER_TOOLS = [find_recipes, recipe_details, search_kroger]
PLAN_TOOLS = [check_budget, submit_plan]

GATHER_SYSTEM = """You collect facts for a meal planner; you do NOT give advice. For the student's request:
1. find_recipes for 2-3 cheap recipes that fit (pass allergies as avoid, vegetarian if asked).
2. recipe_details for each recipe you pick.
3. search_kroger once, for the main ingredients of those recipes (skip salt, pepper, water, spices).
Then reply with just DONE."""

PLAN_SYSTEM = """You plan a week of cheap meals for a broke college student from the facts below
(their request, cookbook recipes, and real prices at their nearest Kroger).
- The plan must FEED the student for 7 days. Decide which meals they want covered from their words (default lunch
  and dinner; "breakfasts" -> breakfast; "dinners" -> dinner only): 7 meals per meal type. Code counts a "for four"
  recipe as 4 meals per batch, other recipes as their calories / 600, and rejects a plan that falls short while money
  is left. Favour cheap, filling recipes and enough batches.
- Choose 2-3 recipes and how many batches of each to cook this week (batches = times cooked; a dinner recipe "for
  four" cooked twice covers 8 dinners). Buy enough for all batches: for each ingredient, ONE Kroger product
  (cheapest per unit that fits) with a quantity.
- Try lists with check_budget (product ids from search_kroger + quantities; 2 cans = quantity 2) as often as you like.
  Code prices them; never multiply or add yourself. If over budget, drop or swap items and check again.
- Respect allergies and diet. Only use recipes, pages and product ids from the facts.
- FINISH by calling submit_plan once with the meals to cover, the final recipes (title, page, batches), items (id, quantity), the
  allergens to avoid and vegetarian as the student asked, and a short note (2-4 sentences: why these recipes, a tip,
  what's left unpriced like salt or spices). The note has NO prices or nutrition numbers: code shows those.
  If submit_plan returns problems, fix them and submit again."""
PROTEIN_GOAL = ("\nThe student set a PROTEIN GOAL of {goal} g per day. Prefer products with high protein_per_dollar "
                "(e.g. dry beans, lentils, eggs, tofu) and recipes with the most protein per serving. The goal is checked on what "
                "the student EATS: each recipe's whole_recipe protein x batches / 7. Pick high-protein recipes and enough "
                "batches (and buy enough for them) while staying in budget.")


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]        # Haiku's gathering conversation
    plan_messages: Annotated[list[AnyMessage], add_messages]   # Opus's planning conversation
    location_id: str                                           # nearest Kroger, from the ZIP field (code)
    budget: float                                              # from the budget field
    protein_goal: int                                          # sidebar slider, g/day, 0 = none (code, not chat)
    tool_calls: Annotated[list[str], operator.add]             # trace for printing


@lru_cache(maxsize=32)
def models(api_key=None):
    """(Haiku with gather tools, Sonnet with plan tools) for one Anthropic key: the student's own, or the server's (.env)."""
    extra = {"api_key": api_key} if api_key else {}
    return (ChatAnthropic(model=GATHER_MODEL, max_tokens=4000, **extra).bind_tools(GATHER_TOOLS),
            ChatAnthropic(model=PLAN_MODEL, max_tokens=4000, **extra).bind_tools(PLAN_TOOLS))


def anthropic_key(config):
    """The student's Anthropic key from the run's config (never from state or a prompt), or None = server key."""
    return (config or {}).get("configurable", {}).get("anthropic_key")


def gatherer(state: State, config: RunnableConfig):
    """Haiku: decide which fetching tool to call next, or say DONE."""
    reply = models(anthropic_key(config))[0].invoke([SystemMessage(GATHER_SYSTEM)] + state["messages"], cache_control=CACHE)
    return {"messages": [reply], "tool_calls": [f"[haiku] {c['name']}({c['args']})" for c in reply.tool_calls]}


def compact(m):
    """Shrink one tool result for Opus: 2 cheapest products per word, recipe ingredients without the cooking steps,
    JSON without spaces. Opus picks products from this; it doesn't need the steps or the 3rd-5th options."""
    data = json.loads(m.content)
    if m.name == "search_kroger":
        data = {term: rows[:2] if isinstance(rows, list) else rows for term, rows in data.items()}   # keep {"error"} as is
    elif m.name == "recipe_details":
        data = {k: v for k, v in data.items() if k not in ("steps", "photo_id")}
    elif m.name == "find_recipes":
        data = [{k: v for k, v in r.items() if k != "photo_id"} for r in data]
    return f"{m.name}: {json.dumps(data, separators=(',', ':'), ensure_ascii=False)}"


def planner(state: State, config: RunnableConfig):
    """Opus: on its first turn gets a plain-text bundle of everything Haiku fetched; picks, checks budget, writes."""
    new = []
    if not state.get("plan_messages"):
        results = [compact(m) for m in state["messages"] if isinstance(m, ToolMessage)]
        new = [HumanMessage(f"Student: {state['messages'][0].content}\nWeekly budget: ${state['budget']}\n\n"
                            "Facts:\n" + "\n".join(results))]
    goal = state.get("protein_goal") or 0
    system = PLAN_SYSTEM + (PROTEIN_GOAL.format(goal=goal) if goal else "")
    reply = models(anthropic_key(config))[1].invoke([SystemMessage(system)] + state.get("plan_messages", []) + new, cache_control=CACHE)
    return {"plan_messages": new + [reply], "tool_calls": [f"[opus] {c['name']}({c['args']})" for c in reply.tool_calls]}


def run_plan_tools(state: State, config: RunnableConfig):
    """Run check_budget / submit_plan for the planner (ToolNode reads the last message of plan_messages)."""
    out = ToolNode(PLAN_TOOLS, messages_key="plan_messages").invoke(state, config)
    return {"plan_messages": out["plan_messages"]}


def final_plan(out):
    """The accepted submit_plan result: the one decided plan (dict), or None. App, eval and CLI all read this."""
    for m in reversed(out.get("plan_messages", [])):
        if isinstance(m, ToolMessage) and m.name == "submit_plan":
            data = json.loads(m.content)
            if data.get("accepted"):
                return data
    return None


def after_gatherer(s):
    """Haiku asked for tools -> run them; said DONE -> hand over to the planner."""
    return "gather_tools" if s["messages"][-1].tool_calls else "planner"


def after_planner(s):
    """Planner asked for a tool -> run it; replied with text only -> stop (no plan)."""
    return "plan_tools" if s["plan_messages"][-1].tool_calls else END


def after_plan_tools(s):
    """An accepted submit_plan ends the run; a what-if or a rejected plan goes back to the planner."""
    return END if final_plan(s) else "planner"


graph = StateGraph(State)
graph.add_node("gatherer", gatherer)
graph.add_node("gather_tools", ToolNode(GATHER_TOOLS))
graph.add_node("planner", planner)
graph.add_node("plan_tools", run_plan_tools)
graph.add_edge(START, "gatherer")
graph.add_conditional_edges("gatherer", after_gatherer, ["gather_tools", "planner"])
graph.add_edge("gather_tools", "gatherer")
graph.add_conditional_edges("planner", after_planner, ["plan_tools", END])
graph.add_conditional_edges("plan_tools", after_plan_tools, ["planner", END])
app = graph.compile()


def trace(out):
    """Every Claude call in order: model, job, tokens, $."""
    total, n = 0, 0
    for m in out["messages"] + out["plan_messages"]:
        u = getattr(m, "usage_metadata", None)
        if not u:
            continue
        n += 1
        model = m.response_metadata.get("model_name", "?")
        p_in, p_out, p_read = next(v for k, v in PRICES.items() if model.startswith(k))
        read = (u.get("input_token_details", {}) or {}).get("cache_read", 0) or 0
        cost = ((u["input_tokens"] - read) * p_in + read * p_read + u["output_tokens"] * p_out) / 1e6
        total += cost
        job = ("TOOLS: " + ", ".join(c["name"] for c in m.tool_calls)) if m.tool_calls else (
            "said: " + m.text[:30].replace("\n", " ") if model.startswith(GATHER_MODEL) else "replied")
        print(f"  {n}. {model[7:]:9} in {u['input_tokens']:>6,} (cache {read:>6,})  out {u['output_tokens']:>5,}  ${cost:.4f}  {job}")
    print(f"  TOTAL ${total:.4f}")


if __name__ == "__main__":
    from browse import nearest_store   # noqa: E402  (kroger/ is on the path via tools.py)
    zip_code, budget, sentence = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    location_id, store = nearest_store(kroger_headers(), zip_code)
    print(f"store: {store} | budget ${budget}\nstudent: {sentence}\n")
    t0 = time.time()
    out = app.invoke({"messages": [HumanMessage(sentence)], "plan_messages": [], "location_id": location_id,
                      "budget": budget, "tool_calls": [], "protein_goal": int(sys.argv[4]) if len(sys.argv) > 4 else 0})
    secs = time.time() - t0
    for i, c in enumerate(out["tool_calls"], 1):
        print(f"tool call {i}: {c[:150]}")
    plan = final_plan(out)
    print("\n--- final plan (JSON, checked by code) ---")
    print(json.dumps({k: v for k, v in plan.items() if k not in ("lines",)}, indent=1)[:2500] if plan else "NO ACCEPTED PLAN")
    print(f"\n{secs:.1f}s\n--- every Claude call ---")
    trace(out)
