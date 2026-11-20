"""Agent piece 1: the code we already built, wrapped as 5 LangGraph tools. Tools = facts and prices; no LLM inside.

Claude only sees each tool's name, docstring and arguments, and picks which to call.
The student's store comes from the graph state (InjectedState), never from Claude: Claude can't pick the wrong store.
"""
import sys
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
for folder in ("kroger", "grocery", "recipes_rag"):
    sys.path.insert(0, str(ROOT / folder))
from browse import browse, token   # noqa: E402  (Kroger)
from match import load_recipes, rank   # noqa: E402  (basket -> recipes)
from search import cards, search   # noqa: E402  (hybrid recipe search + diet fields)

_headers = {}
_labels = {}   # product name -> package nutrition from its Kroger label (filled by search_kroger, read by check_budget)
_recipes = load_recipes()


def kroger_headers():
    """One Kroger token for the whole run (valid 30 min)."""
    if "h" not in _headers:
        _headers["h"] = token()
    return _headers["h"]


def cookable(c):
    """A card the student can actually cook and we can price: has its own ingredient lines, not only
    'see p.94' references (menu cards) and not an idea card with no list."""
    items = [i for g in c["ingredient_groups"] for i in g["items"]]
    return bool(items) and not all("(p." in i for i in items)


def card_summary(c):
    """The few fields Claude needs about a recipe card (keeps tool results short = fewer tokens)."""
    return {"title": c["title"], "page": c["book_page"], "category": c["category"],
            "book_price": f"${c['unit_cost']}/{c['cost_unit']}" if c["unit_cost"] is not None else None,
            "allergens": sorted(c.get("allergens", [])), "vegetarian": c.get("vegetarian"), "photo_id": c["photo_id"],
            "nutrition": c.get("nutrition")}   # USDA, computed by code; null for idea cards


@tool
def search_kroger(terms: list[str], state: Annotated[dict, InjectedState]) -> dict:
    """Search the student's nearest Kroger for grocery items. Returns the 5 cheapest per unit for each term,
    with real prices and protein per package from the product's label (null if Kroger has no label).
    Use plain grocery words like ["rice", "black beans", "eggs"]."""
    out = {}
    for t in terms:
        try:
            rows = browse(kroger_headers(), state["location_id"], t)[:5]
        except RuntimeError as e:          # Kroger down / rate-limited after retries: tell Claude, don't crash
            out[t] = {"error": str(e)}
            continue
        out[t] = []
        for r in rows:
            n = r["nutrition"]
            _labels[r["name"].lower()] = n
            out[t].append({"name": r["name"], "size": r["size"], "price": r["best"], "on_sale": bool(r["promo"]),
                           "unit_price": f"${r['unit_price']}/{r['unit']}" if r["unit_price"] else None,
                           "protein_g": n["protein_g"] if n else None,
                           "protein_per_dollar": round(n["protein_g"] / r["best"], 1) if n else None})
    return out


@tool
def find_recipes(text: str, avoid: list[str] = [], vegetarian: bool = False) -> list[dict]:
    """Search the Good and Cheap cookbook for recipes matching a description like "warm soup with beans".
    avoid: allergens to exclude, only from peanut, tree_nut, milk, egg, wheat, soy, fish, shellfish, sesame.
    vegetarian: true to exclude meat and fish. Returns the top 3 recipes with page numbers."""
    hits = search(text, k=10, avoid=set(avoid), vegetarian=vegetarian)          # look deeper, then keep cookable ones
    return [card_summary(c) for c, _, _ in hits if cookable(c)][:3]


@tool
def recipes_for_basket(items: list[str]) -> list[dict]:
    """Given grocery product names the student is buying, return up to 5 cookbook recipes that use them,
    with what they already have and what is still missing."""
    return [{**card_summary(r["card"]), "have": r["have"], "missing": r["missing"]} for r in rank(items, _recipes)]


@tool
def recipe_details(title: str, page: int | None = None) -> dict:
    """Full ingredients and steps for one cookbook recipe, by its exact title (and page, if two share a title)."""
    same = [c for c in cards if c["title"].lower() == title.lower() and cookable(c)
            and (page is None or c["book_page"] == page)]
    c = same[0] if same else None
    if c is None:
        return {"error": f"no recipe titled {title!r}"}
    groups = {(g["name"] or "ingredients"): g["items"] for g in c["ingredient_groups"]}
    return {**card_summary(c), "makes": c["makes"], "ingredients": groups, "steps": c["steps"]}


class Item(BaseModel):
    """One line of the shopping list."""
    name: str
    price: float      # price of ONE unit, exactly as search_kroger returned it
    quantity: int = 1


@tool
def check_budget(items: list[Item], state: Annotated[dict, InjectedState]) -> dict:
    """Price the shopping list: code multiplies price x quantity for each line, adds the lines and compares with
    the student's budget, and adds up calories / protein / carbs / fiber / sugar from each product's Kroger label.
    Use the EXACT product names from search_kroger. ALWAYS use this; never multiply or add yourself."""
    lines, week, no_label = [], {"calories": 0, "protein_g": 0, "carbs_g": 0, "fiber_g": 0, "sugar_g": 0}, []
    for i in items:
        n = _labels.get(i.name.lower())
        lines.append({"name": i.name, "price": i.price, "quantity": i.quantity, "line_total": round(i.price * i.quantity, 2),
                      "protein_g": n["protein_g"] * i.quantity if n else None})
        if n:
            for k in week:
                week[k] += n.get(k, 0) * i.quantity
        else:
            no_label.append(i.name)
    total = round(sum(l["line_total"] for l in lines), 2)
    out = {"lines": lines, "total": total, "budget": state["budget"], "left": round(state["budget"] - total, 2),
            "within_budget": total <= state["budget"],
            "nutrition_week": week, "protein_g_per_day": round(week["protein_g"] / 7), "no_label": no_label}
    goal = state.get("protein_goal") or 0          # sidebar slider, g/day; 0 = no goal
    if goal:
        out["protein_goal_g_per_day"] = goal
        out["goal_met"] = out["protein_g_per_day"] >= goal
        out["protein_short_g_per_day"] = max(goal - out["protein_g_per_day"], 0)
    return out


TOOLS = [search_kroger, find_recipes, recipes_for_basket, recipe_details, check_budget]
