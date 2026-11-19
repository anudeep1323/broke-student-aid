"""Agent piece 4: Haiku 5.5 gathers facts (fetching jobs), Opus 5.5 decides and writes (judgment jobs).

gatherer (Haiku) <-> gather tools ... --DONE--> planner (Opus) <-> check_budget ... --> answer --> END
Usage: python3 -I agent/graph.py 45202 25 "I'm broke till Friday, no peanuts, tired of rice, want something warm"
"""
import json
import operator
import sys
import time
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools import check_budget, find_recipes, kroger_headers, recipe_details, search_kroger   # noqa: E402

GATHER_MODEL, PLAN_MODEL = "claude-haiku-5-5", "claude-opus-5-5"
PRICES = {  # $ per million tokens: input, output, cache read
    PLAN_MODEL: (4.00, 20.00, 0.20),
    GATHER_MODEL: (0.10, 0.50, 0.01),
}
CACHE = {"type": "ephemeral"}   # top-level auto-caching: repeat calls re-read earlier turns from cache
GATHER_TOOLS = [find_recipes, recipe_details, search_kroger]
PLAN_TOOLS = [check_budget]

GATHER_SYSTEM = """You collect facts for a meal planner; you do NOT give advice. For the student's request:
1. find_recipes for 2-3 cheap recipes that fit (pass allergies as avoid, vegetarian if asked).
2. recipe_details for each recipe you pick.
3. search_kroger once, for the main ingredients of those recipes (skip salt, pepper, water, spices).
Then reply with just DONE."""

PLAN_SYSTEM = """You plan a week of cheap meals for a broke college student from the facts below
(their request, cookbook recipes, and real prices at their nearest Kroger).
- Choose 2-3 recipes and, for each ingredient to buy, ONE Kroger product (cheapest per unit that fits).
- Total your picks with check_budget (never add yourself); if over budget, drop or swap items and check again.
- Respect allergies and diet. Every price, product and page must come from the facts.
- Then write the answer, under 150 words: recipes (title + page), what to buy (product, size, price),
  the total and what's left exactly as check_budget returned it, and anything left unpriced."""


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]        # Haiku's gathering conversation
    plan_messages: Annotated[list[AnyMessage], add_messages]   # Opus's planning conversation
    location_id: str                                           # nearest Kroger, from the ZIP field (code)
    budget: float                                              # from the budget field
    tool_calls: Annotated[list[str], operator.add]             # trace for printing


gather_llm = ChatAnthropic(model=GATHER_MODEL, max_tokens=4000).bind_tools(GATHER_TOOLS)
plan_llm = ChatAnthropic(model=PLAN_MODEL, max_tokens=4000).bind_tools(PLAN_TOOLS)


def gatherer(state: State):
    """Haiku: decide which fetching tool to call next, or say DONE."""
    reply = gather_llm.invoke([SystemMessage(GATHER_SYSTEM)] + state["messages"], cache_control=CACHE)
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


def planner(state: State):
    """Opus: on its first turn gets a plain-text bundle of everything Haiku fetched; picks, checks budget, writes."""
    new = []
    if not state.get("plan_messages"):
        results = [compact(m) for m in state["messages"] if isinstance(m, ToolMessage)]
        new = [HumanMessage(f"Student: {state['messages'][0].content}\nWeekly budget: ${state['budget']}\n\n"
                            "Facts:\n" + "\n".join(results))]
    reply = plan_llm.invoke([SystemMessage(PLAN_SYSTEM)] + state.get("plan_messages", []) + new, cache_control=CACHE)
    return {"plan_messages": new + [reply], "tool_calls": [f"[opus] {c['name']}({c['args']})" for c in reply.tool_calls]}


def run_plan_tools(state: State):
    """Run check_budget for Opus (ToolNode reads the last message of plan_messages)."""
    out = ToolNode(PLAN_TOOLS, messages_key="plan_messages").invoke(state)
    return {"plan_messages": out["plan_messages"]}


graph = StateGraph(State)
graph.add_node("gatherer", gatherer)
graph.add_node("gather_tools", ToolNode(GATHER_TOOLS))
graph.add_node("planner", planner)
graph.add_node("plan_tools", run_plan_tools)
graph.add_edge(START, "gatherer")
graph.add_conditional_edges("gatherer", lambda s: "gather_tools" if s["messages"][-1].tool_calls else "planner",
                            ["gather_tools", "planner"])
graph.add_edge("gather_tools", "gatherer")
graph.add_conditional_edges("planner", lambda s: "plan_tools" if s["plan_messages"][-1].tool_calls else END,
                            ["plan_tools", END])
graph.add_edge("plan_tools", "planner")
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
            "said: " + m.text[:30].replace("\n", " ") if model.startswith(GATHER_MODEL) else "WROTE THE ANSWER")
        print(f"  {n}. {model[7:]:9} in {u['input_tokens']:>6,} (cache {read:>6,})  out {u['output_tokens']:>5,}  ${cost:.4f}  {job}")
    print(f"  TOTAL ${total:.4f}")


if __name__ == "__main__":
    from browse import nearest_store   # noqa: E402  (kroger/ is on the path via tools.py)
    zip_code, budget, sentence = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    location_id, store = nearest_store(kroger_headers(), zip_code)
    print(f"store: {store} | budget ${budget}\nstudent: {sentence}\n")
    t0 = time.time()
    out = app.invoke({"messages": [HumanMessage(sentence)], "plan_messages": [], "location_id": location_id,
                      "budget": budget, "tool_calls": []})
    secs = time.time() - t0
    for i, c in enumerate(out["tool_calls"], 1):
        print(f"tool call {i}: {c[:150]}")
    print(f"\n--- answer (Opus) ---\n{out['plan_messages'][-1].text}\n\n{secs:.1f}s\n--- every Claude call ---")
    trace(out)
