"""Agent piece 1: the code we already built, wrapped as 5 LangGraph tools. Tools = facts and prices; no LLM inside.

Claude only sees each tool's name, docstring and arguments, and picks which to call.
The student's store comes from the graph state (InjectedState), never from Claude: Claude can't pick the wrong store.
"""
import sys
import time
from pathlib import Path
from typing import Annotated, Literal

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
for folder in ("kroger", "grocery", "recipes_rag"):
    sys.path.insert(0, str(ROOT / folder))
from browse import browse, token   # noqa: E402  (Kroger)
from match import load_recipes, rank   # noqa: E402  (basket -> recipes)
from search import cards, search   # noqa: E402  (hybrid recipe search + diet fields)

_headers = {}
_products = {}  # (store, Kroger productId) -> name, size, price, label. Filled by search_kroger, read by check_budget:
                # the only place a price comes from (Claude never types one)
_recipes = load_recipes()


def kroger_headers():
    """A Kroger token, renewed after 25 min: tokens die at 30 min, and the app runs for hours (that was the HTTP 401)."""
    if "h" not in _headers or time.time() - _headers["at"] > 25 * 60:
        _headers["h"], _headers["at"] = token(), time.time()
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
    each with an id (pass it to check_budget), real price, and protein per package from its label (null if none).
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
            _products[(state["location_id"], r["product_id"])] = {"name": r["name"], "size": r["size"],
                                                                   "price": r["best"], "nutrition": n}
            out[t].append({"id": r["product_id"], "name": r["name"], "size": r["size"], "price": r["best"], "on_sale": bool(r["promo"]),
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
    """One line of the shopping list: WHICH product and HOW MANY. No price: code looks it up by id."""
    id: str           # the product's id from search_kroger
    quantity: int = 1


def price_items(items, state):
    """Code prices a list of (id, quantity): real price, size and label looked up by id; totals, nutrition, goal.
    Shared by check_budget (what-ifs) and submit_plan (the final list)."""
    lines, week, no_label, unknown = [], {"calories": 0, "protein_g": 0, "carbs_g": 0, "fiber_g": 0, "sugar_g": 0}, [], []
    for i in items:
        p = _products.get((state["location_id"], i.id))
        if p is None:                       # not from search_kroger (typo or made up): refuse, never guess a price
            unknown.append(i.id)
            continue
        n = p["nutrition"]
        lines.append({"id": i.id, "name": p["name"], "size": p["size"], "price": p["price"], "quantity": i.quantity,
                      "line_total": round(p["price"] * i.quantity, 2), "protein_g": n["protein_g"] * i.quantity if n else None})
        if n:
            for k in week:
                week[k] += n.get(k, 0) * i.quantity
        else:
            no_label.append(p["name"])
    total = round(sum(l["line_total"] for l in lines), 2)
    out = {"lines": lines, "total": total, "budget": state["budget"], "left": round(state["budget"] - total, 2),
           "within_budget": total <= state["budget"],
           "nutrition_week": week, "protein_g_per_day": round(week["protein_g"] / 7), "no_label": no_label}
    if unknown:
        out["unknown_ids"] = unknown
    goal = state.get("protein_goal") or 0          # sidebar slider, g/day; 0 = no goal
    if goal:
        out["protein_goal_g_per_day"] = goal
        out["goal_met"] = out["protein_g_per_day"] >= goal
        out["protein_short_g_per_day"] = max(goal - out["protein_g_per_day"], 0)
    return out


@tool
def check_budget(items: list[Item], state: Annotated[dict, InjectedState]) -> dict:
    """Try a shopping list (a "what if"): give each product's id from search_kroger and a quantity; code looks up the
    real price, multiplies, adds, compares with the budget and sums calories / protein / carbs / fiber / sugar from
    the Kroger labels. Use it as often as you like; never add or multiply yourself."""
    return price_items(items, state)


class RecipePick(BaseModel):
    """One cookbook recipe in the final plan."""
    title: str        # exact title from the recipe tools
    page: int         # its page
    batches: int = Field(1, ge=1, le=7)   # how many times the student cooks it this week


class Plan(BaseModel):
    """The final, decided plan. Code checks it and shows every number; the note carries no numbers."""
    meals: list[Literal["breakfast", "lunch", "dinner"]] = ["lunch", "dinner"]   # meals the student wants covered, 7 days
    recipes: list[RecipePick]
    items: list[Item]                 # product ids from search_kroger + quantities
    avoid: list[str] = []             # allergens the student must avoid: peanut, tree_nut, milk, egg, wheat, soy, fish, shellfish, sesame
    vegetarian: bool = False
    note: str                         # 2-4 friendly sentences for the student: why these recipes, tips, what's unpriced. NO prices or nutrition numbers


@tool
def submit_plan(plan: Plan, state: Annotated[dict, InjectedState]) -> dict:
    """Submit the FINAL plan (call once, at the end). Code checks it: every id known, every recipe real and cookable,
    total within budget, no recipe containing an allergen in avoid (or meat if vegetarian). If accepted, code shows the
    student every price and nutrition number; if not, it returns the problems: fix them and submit again."""
    priced = price_items(plan.items, state)
    problems = []
    if priced.get("unknown_ids"):
        problems.append(f"unknown product ids {priced['unknown_ids']}: use ids exactly as search_kroger returned them")
    if not priced["within_budget"]:
        problems.append(f"total ${priced['total']} is over the ${priced['budget']} budget by ${-priced['left']:.2f}: drop or swap items")
    if not plan.items:
        problems.append("no items: the student needs a shopping list")
    recipes = []
    for r in plan.recipes:
        c = next((c for c in cards if c["title"].lower() == r.title.lower() and c["book_page"] == r.page and cookable(c)), None)
        if c is None:
            problems.append(f"no cookable recipe {r.title!r} on page {r.page}")
            continue
        bad = sorted(set(c.get("allergens", [])) & set(plan.avoid))
        if bad or (plan.vegetarian and c.get("vegetarian") == "no"):
            problems.append(f"{c['title']} (p.{c['book_page']}) breaks the diet: {bad or 'not vegetarian'}")
        recipes.append({**card_summary(c), "batches": r.batches})
    if not plan.recipes:
        problems.append("no recipes: pick 2-3 from the recipe tools")
    target = 7 * len(set(plan.meals))
    planned = sum(meals_from(r) for r in recipes)
    budget_limited = planned < target and priced["total"] >= 0.9 * priced["budget"]   # money really ran out
    if planned < target and not budget_limited and not problems:
        problems.append(f"covers {planned} of {target} meals ({', '.join(plan.meals)} x 7 days) and "
                        f"${priced['left']:.2f} is left: add batches or a cheap, filling recipe, then submit again")
    if problems:
        return {"accepted": False, "problems": problems}
    week = {"meals": sorted(set(plan.meals), key=MEAL_ORDER.index), "meals_target": target, "meals_planned": planned,
            "budget_limited": budget_limited, "calendar": calendar(recipes, sorted(set(plan.meals), key=MEAL_ORDER.index))}
    return {"accepted": True, "recipes": recipes, **priced, **eaten_nutrition(recipes, state), **week,
            "avoid": plan.avoid, "vegetarian": plan.vegetarian, "note": plan.note}


KCAL_PER_MEAL = 600                       # one meal for a student (~2,000 kcal/day over 3 meals); a setting
MEAL_ORDER = ["breakfast", "lunch", "dinner"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def meals_from(r):
    """How many meals one picked recipe gives this week. 'for four' x 2 batches = 8. Pieces or unknown servings
    (24 muffins, 'Oatmeal'): whole-recipe kcal / 600, so nothing is guessed about portion sizes."""
    n = r.get("nutrition")
    if n and n.get("per") == "serving" and isinstance(n.get("servings"), (int, float)):
        return int(n["servings"] * r["batches"])
    if n:
        return max(1, round(n["whole_recipe"]["calories"] * r["batches"] / KCAL_PER_MEAL))
    return r["batches"]


def calendar(recipes, meals):
    """Code lays the meals out Mon-Sun: breakfast slots take breakfast recipes first, lunch/dinner the others;
    recipes take turns so the week isn't 7 days of one dish. Empty slot = None (not covered)."""
    pools = {"breakfast": [], "main": []}
    for r in recipes:
        pools["breakfast" if r["category"] == "breakfast" else "main"].append([r["title"], meals_from(r)])

    def take(order):
        for pool in order:
            alive = [x for x in pools[pool] if x[1] > 0]
            if alive:
                alive[0][1] -= 1
                pools[pool].append(pools[pool].pop(pools[pool].index(alive[0])))   # rotate: next time another recipe
                return alive[0][0]
        return None

    return {d: {m: take(["breakfast", "main"] if m == "breakfast" else ["main", "breakfast"]) for m in meals} for d in DAYS}


def eaten_nutrition(recipes, state):
    """What the student EATS this week: each recipe's USDA totals x batches (not the groceries bought, which include
    leftovers like a whole bag of sugar). Also servings planned, and the protein goal checked against what's eaten."""
    week = dict.fromkeys(["calories", "protein_g", "carbs_g", "fiber_g", "sugar_g"], 0)
    servings, uncounted = 0, []
    for r in recipes:
        n = r.get("nutrition")
        if not n:
            uncounted.append(r["title"])
            continue
        for k in week:
            week[k] += n["whole_recipe"][k] * r["batches"]
        if n.get("per") == "serving" and isinstance(n.get("servings"), (int, float)):
            servings += n["servings"] * r["batches"]     # people servings only (muffins/cups aren't meals)
    out = {"eaten_week": week, "eaten_per_day": {k: round(v / 7) for k, v in week.items()},
           "servings_planned": servings, "recipes_without_nutrition": uncounted}
    goal = state.get("protein_goal") or 0
    if goal:   # the goal is about what the student eats, so it's checked here, not on the groceries
        out["protein_goal_g_per_day"] = goal
        out["goal_met"] = out["eaten_per_day"]["protein_g"] >= goal
        out["protein_short_g_per_day"] = max(goal - out["eaten_per_day"]["protein_g"], 0)
    return out


TOOLS = [search_kroger, find_recipes, recipes_for_basket, recipe_details, check_budget, submit_plan]
