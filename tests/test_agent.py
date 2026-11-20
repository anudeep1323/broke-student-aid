"""Unit tests for the agent's wiring (graph.py) and the Browse tab's basket matching (grocery/). No LLM calls.

Run: ../.venv/bin/python3 -m pytest tests/ -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for folder in ("agent", "grocery", "recipes_rag", "kroger"):
    sys.path.insert(0, str(ROOT / folder))
pytest.importorskip("langgraph")
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage   # noqa: E402
from langgraph.graph import END   # noqa: E402

import graph   # noqa: E402   (builds the graph; no Claude call until invoke)
from ingredients import normalise   # noqa: E402
from match import covers, rank, words   # noqa: E402


def tool_msg(name, data):
    return ToolMessage(content=json.dumps(data), name=name, tool_call_id="t1")


def ask(name):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "t1"}])


# 1. final_plan: the ONE accepted plan, which app, eval and CLI all read
def test_final_plan_picks_the_accepted_one():
    msgs = [tool_msg("check_budget", {"total": 20.23}),                       # a what-if: never the plan
            tool_msg("submit_plan", {"accepted": False, "problems": ["over budget"]}),
            tool_msg("submit_plan", {"accepted": True, "total": 18.73})]
    assert graph.final_plan({"plan_messages": msgs})["total"] == 18.73


def test_final_plan_none_without_acceptance():
    msgs = [tool_msg("check_budget", {"total": 20.23}), tool_msg("submit_plan", {"accepted": False, "problems": []})]
    assert graph.final_plan({"plan_messages": msgs}) is None
    assert graph.final_plan({}) is None


# 2. Routing: where the graph goes next
def test_routing():
    assert graph.after_gatherer({"messages": [ask("find_recipes")]}) == "gather_tools"
    assert graph.after_gatherer({"messages": [AIMessage(content="DONE")]}) == "planner"
    assert graph.after_planner({"plan_messages": [ask("check_budget")]}) == "plan_tools"
    assert graph.after_planner({"plan_messages": [AIMessage(content="sorry, Kroger is down")]}) == END
    rejected = {"plan_messages": [tool_msg("submit_plan", {"accepted": False, "problems": ["x"]})]}
    accepted = {"plan_messages": [tool_msg("submit_plan", {"accepted": True})]}
    whatif = {"plan_messages": [tool_msg("check_budget", {"total": 5})]}
    assert graph.after_plan_tools(rejected) == "planner"      # fix and resubmit
    assert graph.after_plan_tools(whatif) == "planner"        # keep planning
    assert graph.after_plan_tools(accepted) == END            # done


# 3. compact(): what the planner reads from Haiku's facts (fewer tokens, nothing important lost)
def test_compact():
    rows = [{"id": str(i), "name": f"P{i}", "price": i} for i in range(5)]
    s = graph.compact(tool_msg("search_kroger", {"rice": rows, "spice": {"error": "HTTP 503"}}))
    data = json.loads(s.split(": ", 1)[1])
    assert [r["id"] for r in data["rice"]] == ["0", "1"]       # 2 cheapest per word
    assert data["spice"] == {"error": "HTTP 503"}               # errors kept as they are
    s = graph.compact(tool_msg("recipe_details", {"title": "Dal", "steps": "long...", "photo_id": "p35", "makes": "for four"}))
    assert "steps" not in s and "photo_id" not in s and "for four" in s


def test_planner_tools_and_prompt():
    assert {t.name for t in graph.PLAN_TOOLS} == {"check_budget", "submit_plan"}
    assert "submit_plan" in graph.PLAN_SYSTEM and "NO prices or nutrition numbers" in graph.PLAN_SYSTEM


# 4. Basket -> recipes (Browse tab)
@pytest.mark.parametrize("line, name", [
    ("2 cloves garlic, finely chopped", "garlic"),
    ("½ to 1 cup coconut milk", "coconut milk"),
    ("2 large or 4 medium potatoes, chopped", "potato"),
    ("1 cup peas, fresh or frozen", "pea"),
    ("salt and pepper", None),                     # basics every student has
    ("black-eyed peas and collards (p. 94)", "black eyed peas and collard"),
])
def test_normalise(line, name):
    assert normalise(line) == name


def test_covers():
    assert words("Kroger® Medium White Eggs") == {"kroger", "medium", "white", "egg"}
    assert covers("Kroger Long Grain Rice", "rice")
    assert not covers("Kroger Vegetable Oil", "olive oil")     # every ingredient word must be in the product


def test_rank_basket():
    dal = ({"title": "Dal"}, {"lentil", "onion", "garlic", "butter"})
    omelette = ({"title": "Omelette"}, {"egg", "butter", "dill"})
    toast = ({"title": "Toast"}, {"bread"})
    out = rank(["Dry Lentils", "Yellow Onion", "Large Eggs"], [omelette, dal, toast])
    assert [r["card"]["title"] for r in out] == ["Dal", "Omelette"]   # Dal uses 2 basket items, Omelette 1, Toast 0
    assert out[0]["have"] == ["lentil", "onion"] and out[0]["missing"] == ["butter", "garlic"]
