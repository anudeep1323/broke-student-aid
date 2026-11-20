"""The FastAPI backend with a fake agent and fake store: checks the HTTP contract the React page relies on. No API calls.

Run: ../.venv/bin/python3 -m pytest tests/ -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient   # noqa: E402
from langchain_core.messages import AIMessage   # noqa: E402

import api.main as m   # noqa: E402

PLAN = {"accepted": True, "note": "Dal twice.", "total": 8.95, "recipes": [], "lines": []}


class FakeApp:
    """Streams 3 states like LangGraph does: tool calls pile up, the last state holds the plan."""
    def stream(self, state, stream_mode):
        assert stream_mode == "values" and state["budget"] == 25.0 and state["protein_goal"] == 80
        base = {"messages": [], "plan_messages": [AIMessage(content="")]}
        yield base | {"tool_calls": ["[haiku] find_recipes({'text': 'dal'})"]}
        yield base | {"tool_calls": ["[haiku] find_recipes({'text': 'dal'})", "[haiku] search_kroger({'terms': ['lentils']})"]}
        yield base | {"tool_calls": ["[haiku] find_recipes({})", "[haiku] search_kroger({})", "[opus] submit_plan({})"], "done": True}


@pytest.fixture
def client(monkeypatch):
    m.store_for.cache_clear()
    monkeypatch.setattr(m, "nearest_store", lambda h, z: ("STORE1", "Test Kroger") if z == "45202" else ([][0], None))
    monkeypatch.setattr(m, "kroger_headers", lambda: {})
    monkeypatch.setattr(m, "agent", lambda: (FakeApp(), {}, lambda s: PLAN if s.get("done") else None))
    return TestClient(m.api)


def events(resp):
    """Parse a server-sent-events body into [(event, data)]."""
    out, ev = [], None
    for line in resp.text.splitlines():
        if line.startswith("event:"):
            ev = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            out.append((ev, json.loads(line.split(":", 1)[1])))
    return out


def test_store(client):
    assert client.get("/api/store?zip=45202").json() == {"location_id": "STORE1", "name": "Test Kroger"}
    assert client.get("/api/store?zip=99999").status_code == 404     # no store near it
    assert client.get("/api/store?zip=4520").status_code == 422      # not 5 digits: rejected before any Kroger call


def test_plan_streams_steps_then_plan(client):
    resp = client.post("/api/plan", json={"sentence": "cheap dal", "zip": "45202", "budget": 25, "protein_goal": 80})
    ev = events(resp)
    assert [e for e, _ in ev] == ["step", "step", "step", "plan", "done"]
    assert [d["text"] for e, d in ev if e == "step"] == ["Searching the cookbook", "Checking prices at your Kroger",
                                                         "Checking the plan (budget, allergens, the whole week)"]
    plan = ev[3][1]
    assert plan["total"] == 8.95 and plan["note"] == "Dal twice." and "seconds" in plan and "cost" in plan


def test_plan_validates_input(client):
    assert client.post("/api/plan", json={"sentence": "x", "zip": "45202", "budget": 25}).status_code == 422   # too short
    assert client.post("/api/plan", json={"sentence": "cheap dal", "zip": "45202", "budget": -5}).status_code == 422
    assert client.post("/api/plan", json={"sentence": "cheap dal", "zip": "abcde", "budget": 25}).status_code == 422


def test_plan_bad_zip_is_an_error_event(client):
    ev = events(client.post("/api/plan", json={"sentence": "cheap dal", "zip": "99999", "budget": 25}))
    assert ev[0][0] == "error" and "No Kroger store" in ev[0][1]["message"]


def test_agent_crash_is_an_error_event(client, monkeypatch):
    class Boom:
        def stream(self, *a, **k):
            raise RuntimeError("Kroger products failed: HTTP 503")
            yield
    monkeypatch.setattr(m, "agent", lambda: (Boom(), {}, lambda s: None))
    ev = events(client.post("/api/plan", json={"sentence": "cheap dal", "zip": "45202", "budget": 25}))
    assert ev == [("error", {"message": "RuntimeError: Kroger products failed: HTTP 503"})]


def test_recipe_and_health(client):
    r = client.get("/api/recipe", params={"title": "Dal", "page": 35}).json()
    assert r["book_page"] == 35 and r["ingredient_groups"] and r["nutrition"]["per_serving"]["protein_g"] > 0
    assert client.get("/api/recipe", params={"title": "Black-Eyed Peas and Collards", "page": 73}).status_code == 404  # menu card
    assert client.get("/api/health").json()["recipes"] > 90
