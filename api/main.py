"""Broke Student Aid API: the same agent and Kroger code the Streamlit app used, behind HTTP for the React page.

GET  /api/store?zip=45202            nearest Kroger (code)
POST /api/plan                        the agent, streamed: one event per step, then the checked JSON plan
GET  /api/products?location_id=&term= Kroger products for the Browse tab (code)
GET  /api/recipe?title=&page=         one full recipe card for the pop-up (code)
GET  /images/<photo_id>.png           recipe photos
Run: python3 -m uvicorn api.main:api --port 8000
"""
import json
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool

ROOT = Path(__file__).resolve().parent.parent
for folder in ("agent", "kroger", "recipes_rag"):
    sys.path.insert(0, str(ROOT / folder))
from browse import browse, nearest_store   # noqa: E402
from tools import cards, cookable, kroger_headers   # noqa: E402   (also loads the search model once)

IMAGES = ROOT / "recipes_rag" / "data" / "images"
api = FastAPI(title="Broke Student Aid")
if IMAGES.exists():
    api.mount("/images", StaticFiles(directory=IMAGES), name="images")

STEP_TEXT = {  # what the student sees for each tool the agent calls
    "find_recipes": "Searching the cookbook", "recipe_details": "Reading recipes", "search_kroger": "Checking prices at your Kroger",
    "check_budget": "Pricing a shopping list", "submit_plan": "Checking the plan (budget, allergens, the whole week)",
}


@lru_cache(maxsize=1)
def agent():
    """The LangGraph app, built once (Haiku gathers, Sonnet plans)."""
    from graph import PRICES, app, final_plan
    return app, PRICES, final_plan


@lru_cache(maxsize=256)
def store_for(zip_code):
    """ZIP -> (locationId, store name). A ZIP's nearest store doesn't change, so it's cached."""
    return nearest_store(kroger_headers(), zip_code)


@api.get("/api/store")
def store(zip: str = Query(pattern=r"^\d{5}$")):
    try:
        location_id, name = store_for(zip)
    except (IndexError, KeyError):
        raise HTTPException(404, f"No Kroger store found near {zip}")
    return {"location_id": location_id, "name": name}


class PlanRequest(BaseModel):
    sentence: str = Field(min_length=3, max_length=500)
    zip: str = Field(pattern=r"^\d{5}$")
    budget: float = Field(gt=0, le=500)
    protein_goal: int = Field(0, ge=0, le=250)


def cost_of(state, prices):
    """$ for every Claude call in one answer (cache reads priced separately)."""
    total = 0
    for m in state["messages"] + state["plan_messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            p_in, p_out, p_read = next(v for k, v in prices.items() if m.response_metadata.get("model_name", "").startswith(k))
            read = (u.get("input_token_details", {}) or {}).get("cache_read", 0) or 0
            total += ((u["input_tokens"] - read) * p_in + read * p_read + u["output_tokens"] * p_out) / 1e6
    return total


def plan_events(req: PlanRequest):
    """Run the agent and yield events as it goes: 'step' for each tool call, then 'plan' (or 'error'), then 'done'."""
    t0 = time.time()
    try:
        location_id, _ = store_for(req.zip)
    except (IndexError, KeyError):
        yield {"event": "error", "data": json.dumps({"message": f"No Kroger store found near {req.zip}"})}
        return
    app, prices, final_plan = agent()
    state, seen = None, 0
    try:
        for state in app.stream({"messages": [HumanMessage(req.sentence)], "plan_messages": [], "location_id": location_id,
                                 "budget": req.budget, "tool_calls": [], "protein_goal": req.protein_goal},
                                stream_mode="values"):
            for call in state.get("tool_calls", [])[seen:]:          # new tool calls since the last step
                name = re.match(r"\[\w+\] (\w+)\(", call)
                tool = name.group(1) if name else "?"
                yield {"event": "step", "data": json.dumps({"tool": tool, "text": STEP_TEXT.get(tool, tool),
                                                            "seconds": round(time.time() - t0)})}
            seen = len(state.get("tool_calls", []))
    except Exception as e:  # noqa: BLE001   (Kroger down, Claude error): tell the page, don't hang it
        yield {"event": "error", "data": json.dumps({"message": f"{type(e).__name__}: {str(e)[:200]}"})}
        return
    plan = final_plan(state) if state else None
    meta = {"seconds": round(time.time() - t0), "cost": round(cost_of(state, prices), 4) if state else 0}
    if plan:
        yield {"event": "plan", "data": json.dumps(plan | meta)}
    else:   # no accepted plan: show the planner's own words, no numbers
        text = state["plan_messages"][-1].text if state and state["plan_messages"] else "Sorry, I couldn't build a plan."
        yield {"event": "error", "data": json.dumps({"message": text} | meta)}
    yield {"event": "done", "data": "{}"}


@api.post("/api/plan")
async def plan(req: PlanRequest):
    """Server-sent events: the agent's steps live, then the checked plan."""
    return EventSourceResponse(iterate_in_threadpool(plan_events(req)))


@api.get("/api/products")
def products(location_id: str, term: str = Query(min_length=2, max_length=40)):
    """Kroger products for one food, cheapest per unit first (code, no LLM)."""
    return browse(kroger_headers(), location_id, term)


@api.get("/api/recipe")
def recipe(title: str, page: int):
    """One full recipe card for the pop-up: ingredients, steps, photo, nutrition."""
    c = next((c for c in cards if c["title"] == title and c["book_page"] == page and cookable(c)), None)
    if c is None:
        raise HTTPException(404, "recipe not found")
    return {k: c[k] for k in ("title", "book_page", "makes", "ingredient_groups", "steps", "photo_id", "nutrition")}


@api.get("/api/health")
def health():
    return {"ok": True, "recipes": len(cards)}
