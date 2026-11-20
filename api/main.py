"""Broke Student Aid API: the same agent and Kroger code the Streamlit app used, behind HTTP for the React page.

GET  /api/store?zip=45202            nearest Kroger (code)
POST /api/plan                        the agent, streamed: one event per step, then the checked JSON plan
GET  /api/products?location_id=&term= Kroger products for the Browse tab (code)
GET  /api/recipe?title=&page=         one full recipe card for the pop-up (code)
GET  /images/<photo_id>.png           recipe photos
POST /api/keys/check                  test the student's keys (free calls), never echoes them
Keys: X-Anthropic-Key, X-Kroger-Id, X-Kroger-Secret headers on every call; used for that request only, never stored
or logged; missing -> the server's .env keys.
Run: python3 -m uvicorn api.main:api --port 8000
"""
import json
import re
import sys
import time
from functools import lru_cache

import anthropic
import requests
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool

ROOT = Path(__file__).resolve().parent.parent
for folder in ("agent", "kroger", "recipes_rag"):
    sys.path.insert(0, str(ROOT / folder))
from browse import browse, nearest_store, token   # noqa: E402
from tools import cards, cookable, kroger_creds, kroger_headers   # noqa: E402   (also loads the search model once)

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


def keys(x_anthropic_key: str | None = Header(None), x_kroger_id: str | None = Header(None),
         x_kroger_secret: str | None = Header(None)) -> dict:
    """The student's keys from request headers, as LangGraph config. Empty -> None -> the server's .env keys."""
    clean = lambda s: (s or "").strip() or None
    return {"anthropic_key": clean(x_anthropic_key), "kroger_id": clean(x_kroger_id), "kroger_secret": clean(x_kroger_secret)}


_stores = {}   # ZIP -> (locationId, name): public store data, the same whoever asks


def store_for(zip_code, creds=None):
    """ZIP -> (locationId, store name). A ZIP's nearest store doesn't change, so it's cached."""
    if zip_code not in _stores:
        _stores[zip_code] = nearest_store(kroger_headers(creds), zip_code)
    return _stores[zip_code]


def kroger_error(e):
    """A Kroger failure as a message the student can act on (never containing a key)."""
    if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code in (400, 401):
        return HTTPException(401, "Kroger rejected the client ID / secret: check them in 🔑 API keys")
    return HTTPException(502, f"Kroger is not answering ({type(e).__name__}); try again in a minute")


@api.get("/api/store")
def store(zip: str = Query(pattern=r"^\d{5}$"), k: dict = Depends(keys)):
    try:
        location_id, name = store_for(zip, kroger_creds({"configurable": k}))
    except IndexError:
        raise HTTPException(404, f"No Kroger store found near {zip}")
    except KeyError:   # no key sent and none in the server's .env
        raise HTTPException(503, "No Kroger keys: add yours in 🔑 API keys")
    except requests.RequestException as e:
        raise kroger_error(e)
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


def plan_events(req: PlanRequest, k: dict):
    """Run the agent and yield events as it goes: 'step' for each tool call, then 'plan' (or 'error'), then 'done'."""
    t0 = time.time()
    try:
        location_id, _ = store_for(req.zip, kroger_creds({"configurable": k}))
    except IndexError:
        yield {"event": "error", "data": json.dumps({"message": f"No Kroger store found near {req.zip}"})}
        return
    except (requests.RequestException, KeyError) as e:
        msg = "No Kroger keys: add yours in 🔑 API keys" if isinstance(e, KeyError) else kroger_error(e).detail
        yield {"event": "error", "data": json.dumps({"message": msg})}
        return
    app, prices, final_plan = agent()
    state, seen = None, 0
    try:
        for state in app.stream({"messages": [HumanMessage(req.sentence)], "plan_messages": [], "location_id": location_id,
                                 "budget": req.budget, "tool_calls": [], "protein_goal": req.protein_goal},
                                config={"configurable": k}, stream_mode="values"):   # keys in config, never in state
            for call in state.get("tool_calls", [])[seen:]:          # new tool calls since the last step
                name = re.match(r"\[\w+\] (\w+)\(", call)
                tool = name.group(1) if name else "?"
                yield {"event": "step", "data": json.dumps({"tool": tool, "text": STEP_TEXT.get(tool, tool),
                                                            "seconds": round(time.time() - t0)})}
            seen = len(state.get("tool_calls", []))
    except anthropic.AuthenticationError:
        yield {"event": "error", "data": json.dumps({"message": "Anthropic rejected the API key: check it in 🔑 API keys"})}
        return
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
async def plan(req: PlanRequest, k: dict = Depends(keys)):
    """Server-sent events: the agent's steps live, then the checked plan."""
    return EventSourceResponse(iterate_in_threadpool(plan_events(req, k)))


@api.get("/api/products")
def products(location_id: str, term: str = Query(min_length=2, max_length=40), k: dict = Depends(keys)):
    """Kroger products for one food, cheapest per unit first (code, no LLM)."""
    try:
        return browse(kroger_headers(kroger_creds({"configurable": k})), location_id, term)
    except requests.RequestException as e:
        raise kroger_error(e)


@api.post("/api/keys/check")
def check_keys(k: dict = Depends(keys)):
    """Test the keys with free calls (Anthropic: list models; Kroger: get a token). Says which key failed, never echoes it."""
    out = {}
    try:
        anthropic.Anthropic(**({"api_key": k["anthropic_key"]} if k["anthropic_key"] else {})).models.list(limit=1)
        out["anthropic"] = {"ok": True, "source": "yours" if k["anthropic_key"] else "server"}
    except anthropic.AuthenticationError:
        out["anthropic"] = {"ok": False, "message": "rejected: check the key"}
    except Exception as e:  # noqa: BLE001   (no server key either, network)
        out["anthropic"] = {"ok": False, "message": "no key" if "api_key" in str(e).lower() else type(e).__name__}
    creds = kroger_creds({"configurable": k})
    try:
        token(*creds) if creds else token()
        out["kroger"] = {"ok": True, "source": "yours" if creds else "server"}
    except KeyError:
        out["kroger"] = {"ok": False, "message": "no key"}
    except requests.RequestException as e:
        out["kroger"] = {"ok": False, "message": kroger_error(e).detail}
    return out


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
