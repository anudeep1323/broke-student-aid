"""Agent piece 1: the code we already built, wrapped as 4 LangGraph tools. Tools = facts and prices; no LLM inside.

Claude only sees each tool's name, docstring and arguments, and picks which to call.
The student's store comes from the graph state (InjectedState), never from Claude: Claude can't pick the wrong store.
"""
import sys
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

ROOT = Path(__file__).resolve().parent.parent
for folder in ("kroger", "grocery", "recipes_rag"):
    sys.path.insert(0, str(ROOT / folder))
from browse import browse, token   # noqa: E402  (Kroger)
from match import load_recipes, rank   # noqa: E402  (basket -> recipes)
from search import cards, search   # noqa: E402  (hybrid recipe search + diet fields)

_headers = {}
_recipes = load_recipes()


def kroger_headers():
    """One Kroger token for the whole run (valid 30 min)."""
    if "h" not in _headers:
        _headers["h"] = token()
    return _headers["h"]


def card_summary(c):
    """The few fields Claude needs about a recipe card (keeps tool results short = fewer tokens)."""
    return {"title": c["title"], "page": c["book_page"], "category": c["category"],
            "book_price": f"${c['unit_cost']}/{c['cost_unit']}" if c["unit_cost"] is not None else None,
            "allergens": sorted(c.get("allergens", [])), "vegetarian": c.get("vegetarian"), "photo_id": c["photo_id"]}


@tool
def search_kroger(terms: list[str], state: Annotated[dict, InjectedState]) -> dict:
    """Search the student's nearest Kroger for grocery items. Returns the 5 cheapest per unit for each term,
    with real prices. Use plain grocery words like ["rice", "black beans", "eggs"]."""
    out = {}
    for t in terms:
        try:
            rows = browse(kroger_headers(), state["location_id"], t)[:5]
        except RuntimeError as e:          # Kroger down / rate-limited after retries: tell Claude, don't crash
            out[t] = {"error": str(e)}
            continue
        out[t] = [{"name": r["name"], "size": r["size"], "price": r["best"], "on_sale": bool(r["promo"]),
                   "unit_price": f"${r['unit_price']}/{r['unit']}" if r["unit_price"] else None} for r in rows]
    return out


@tool
def find_recipes(text: str, avoid: list[str] = [], vegetarian: bool = False) -> list[dict]:
    """Search the Good and Cheap cookbook for recipes matching a description like "warm soup with beans".
    avoid: allergens to exclude, only from peanut, tree_nut, milk, egg, wheat, soy, fish, shellfish, sesame.
    vegetarian: true to exclude meat and fish. Returns the top 3 recipes with page numbers."""
    return [card_summary(c) for c, _, _ in search(text, avoid=set(avoid), vegetarian=vegetarian)]


@tool
def recipes_for_basket(items: list[str]) -> list[dict]:
    """Given grocery product names the student is buying, return up to 5 cookbook recipes that use them,
    with what they already have and what is still missing."""
    return [{**card_summary(r["card"]), "have": r["have"], "missing": r["missing"]} for r in rank(items, _recipes)]


@tool
def recipe_details(title: str) -> dict:
    """Full ingredients and steps for one cookbook recipe, by its exact title (for 'how do I cook it?' or swaps)."""
    c = next((c for c in cards if c["title"].lower() == title.lower()), None)
    if c is None:
        return {"error": f"no recipe titled {title!r}"}
    groups = {(g["name"] or "ingredients"): g["items"] for g in c["ingredient_groups"]}
    return {**card_summary(c), "makes": c["makes"], "ingredients": groups, "steps": c["steps"]}


@tool
def check_budget(prices: list[float], state: Annotated[dict, InjectedState]) -> dict:
    """Add up the prices of the items you plan to suggest and compare with the student's budget.
    ALWAYS use this for totals; never add prices yourself."""
    total = round(sum(prices), 2)
    return {"total": total, "budget": state["budget"], "left": round(state["budget"] - total, 2),
            "within_budget": total <= state["budget"]}


TOOLS = [search_kroger, find_recipes, recipes_for_basket, recipe_details, check_budget]
