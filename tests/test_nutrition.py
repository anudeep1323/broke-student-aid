"""Unit tests for the plain-code parts (no LLM): parsing, grams, food matching, servings, label math, budget math.

They read the saved USDA answers (recipes_rag/data/usda_cache.json), so no internet and no cost.
Run: ../.venv/bin/python3 -m pytest tests/ -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for folder in ("recipes_rag", "kroger", "agent"):
    sys.path.insert(0, str(ROOT / folder))
from nutrition import CACHE, grams, parse, servings, usda   # noqa: E402

cache = json.loads(CACHE.read_text()) if CACHE.exists() else None
needs_cache = pytest.mark.skipif(cache is None, reason="run recipes_rag/nutrition.py once to save USDA answers")


# 1. Reading a recipe line
@pytest.mark.parametrize("line, expected", [
    ("1½ cups sugar", (1.5, "cup", "sugar")),
    ("1 cup dry lentils, rinsed", (1.0, "cup", "dry lentils")),
    ("½ tsp chili flakes (or fresh chili)", (0.5, "tsp", "chili flakes")),
    ("1½ lb pork shoulder or butt, cubed", (1.5, "lb", "pork shoulder")),   # "or" -> first choice
    ("6 to 8 cobs corn", (6.0, "ear", "corn")),                             # range -> first number
    ("salt and pepper", None),                                              # no amount -> not counted
])
def test_parse(line, expected):
    assert parse(line) == expected


# 2. Units -> grams, using USDA's own portions
@needs_cache
@pytest.mark.parametrize("amount, unit, food, expected_g", [
    (1, "cup", "lentils", 192),      # USDA: 1 cup lentils = 192 g
    (1, "medium", "onion", 110),     # the bug we fixed: was 14 g ("1 slice, medium")
    (3, "clove", "garlic", 9),       # 1 clove = 3 g
    (4, None, "eggs", 176),          # no unit -> medium egg, 44 g each
    (1, "lb", "pork", 453.6),        # weights don't need USDA portions
])
def test_grams(amount, unit, food, expected_g):
    assert grams(amount, unit, usda(food, cache)) == pytest.approx(expected_g, abs=1)


# 3. Food words -> the hand-checked USDA food (never a guess)
@needs_cache
@pytest.mark.parametrize("food, usda_name", [
    ("eggs", "Egg, whole, raw, fresh"),                     # search's top hit was "Bagels, egg"
    ("milk", "Milk, whole, 3.25% milkfat, with added vitamin D"),   # search's top hit was "Crackers, milk"
    ("egg yolk", "Egg, yolk, raw, fresh"),                  # specific beats general
    ("coconut milk", "Nuts, coconut milk, raw (liquid expressed from grated meat and water)"),
    ("dried pinto", "Beans, pinto, mature seeds, cooked, boiled, without salt"),
])
def test_food_match(food, usda_name):
    assert usda(food, cache)["name"] == usda_name


def test_unknown_food_is_missed_not_guessed():
    assert usda("dragon fruit", {}) is None   # not on the list -> None, before any USDA call


# 4. Servings from the card's "makes" text
@pytest.mark.parametrize("makes, expected", [
    ("for four", (4, "serving")), ("for two, or four as a side", (2, "serving")), ("serves four to six", (4, "serving")),
    ("twenty-four small muffins", (24, "muffin")), ("makes four pizzas", (4, "pizza")), ("twelve", (12, "piece")),
    ("ten to fourteen pancakes", (10, "pancake")),          # range -> lower number
    ("three and a half cups", (3.5, "cup")), ("makes twenty-four half eggs", (24, "half egg")),
    (None, (None, None)), ("a big pot", (None, None)),      # nothing to read -> unknown, not guessed
])
def test_servings(makes, expected):
    assert servings(makes) == expected


# 5. Kroger label -> whole package
def test_kroger_label_whole_package():
    from browse import nutrition
    product = {"nutritionInformation": [{
        "servingsPerPackage": {"value": 14},
        "nutrients": [{"displayName": "Protein", "quantity": 9}, {"displayName": "Calories", "quantity": 160},
                      {"displayName": "Total Carbohydrate", "quantity": 29}, {"displayName": "Dietary Fiber", "quantity": 5},
                      {"displayName": "Sugar", "quantity": 1}]}]}
    assert nutrition(product) == {"protein_g": 126, "calories": 2240, "carbs_g": 406, "fiber_g": 70,
                                  "sugar_g": 14, "servings": 14}


def test_kroger_no_label():
    from browse import nutrition
    assert nutrition({}) is None


# 6. Budget + nutrition math in check_budget (code, not the AI): Claude sends ids + quantities, code owns prices
LENTILS = {"protein_g": 126, "calories": 2240, "carbs_g": 406, "fiber_g": 70, "sugar_g": 14}
BEANS = {"protein_g": 21, "calories": 385, "carbs_g": 70, "fiber_g": 21, "sugar_g": 0}


@pytest.fixture
def tools():
    pytest.importorskip("langgraph")
    import tools
    tools._products.clear()
    tools._products.update({
        ("S1", "L16"): {"name": "Kroger Pinto Beans", "size": "16 oz", "price": 1.19, "nutrition": {**LENTILS, "protein_g": 91}},
        ("S1", "L32"): {"name": "Kroger Pinto Beans", "size": "32 oz", "price": 2.29, "nutrition": {**LENTILS, "protein_g": 182}},
        ("S1", "LEN"): {"name": "Lentils", "size": "16 oz", "price": 1.49, "nutrition": LENTILS},
        ("S1", "BEA"): {"name": "Beans", "size": "15 oz", "price": 1.09, "nutrition": BEANS},
        ("S1", "GAR"): {"name": "Garlic", "size": "6 oz", "price": 2.99, "nutrition": None},
    })
    return tools


def test_check_budget_math(tools):
    out = tools.check_budget.func(
        [tools.Item(id="LEN", quantity=2), tools.Item(id="BEA", quantity=2), tools.Item(id="GAR")],
        {"location_id": "S1", "budget": 10.0, "protein_goal": 80})
    assert [l["price"] for l in out["lines"]] == [1.49, 1.09, 2.99]       # prices from code, not from Claude
    assert [l["line_total"] for l in out["lines"]] == [2.98, 2.18, 2.99]   # 1.09 x 2 = 2.18
    assert out["total"] == 8.15 and out["left"] == 1.85 and out["within_budget"]
    assert out["nutrition_week"]["protein_g"] == 126 * 2 + 21 * 2          # 294 g
    assert out["protein_g_per_day"] == 42                                 # 294 / 7
    assert out["no_label"] == ["Garlic"]
    assert out["goal_met"] is False and out["protein_short_g_per_day"] == 38


def test_same_name_different_size(tools):
    """The 91 g vs 182 g bug: three sizes share the name 'Kroger Pinto Beans'. The id picks the right label."""
    out = tools.check_budget.func([tools.Item(id="L32")], {"location_id": "S1", "budget": 10.0})
    assert out["lines"][0]["size"] == "32 oz" and out["lines"][0]["protein_g"] == 182 and out["total"] == 2.29


def test_unknown_id_is_refused(tools):
    """A typo or made-up id gets no price at all (never a guessed one) and is reported back."""
    out = tools.check_budget.func([tools.Item(id="LEN"), tools.Item(id="FAKE")], {"location_id": "S1", "budget": 10.0})
    assert out["total"] == 1.49 and len(out["lines"]) == 1 and out["unknown_ids"][0] == "FAKE"


def test_ids_are_per_store(tools):
    out = tools.check_budget.func([tools.Item(id="LEN")], {"location_id": "OTHER_STORE", "budget": 10.0})
    assert out["total"] == 0 and out["unknown_ids"][0] == "LEN"          # a price from store S1 isn't used at another store


def test_over_budget(tools):
    out = tools.check_budget.func([tools.Item(id="LEN", quantity=10)], {"location_id": "S1", "budget": 10.0})
    assert out["total"] == 14.9 and out["left"] == -4.9 and not out["within_budget"]
    assert "goal_met" not in out                                          # no goal set -> no goal fields


# 7. Only cookable cards reach the agent
def test_cookable(tools):
    menu = {"ingredient_groups": [{"items": ["black-eyed peas and collards (p. 94)", "scones (p. 22) (optional)"]}]}
    idea = {"ingredient_groups": []}
    real = {"ingredient_groups": [{"items": ["1 cup dried black-eyed peas", "1 large bunch collards"]}]}
    assert not tools.cookable(menu) and not tools.cookable(idea) and tools.cookable(real)


# 8. A whole recipe: sum the lines, skip spices, report misses, divide by servings
@needs_cache
def test_recipe_nutrition():
    from nutrition import recipe_nutrition
    card = {"makes": "for two", "ingredient_groups": [{"name": None, "items": [
        "1 cup dry lentils, rinsed", "1 tsp salt", "salsa"]}]}
    out = recipe_nutrition(card, cache)
    lentil_protein = 192 / 100 * cache["Lentils, raw"]["per100"]["protein_g"]   # 1 cup = 192 g
    assert out["total"]["protein_g"] == round(lentil_protein)
    assert out["per_serving"]["protein_g"] == round(lentil_protein / 2)
    assert out["skipped"] == ["1 tsp salt"] and out["missed"] == ["salsa"] and len(out["counted"]) == 1


@needs_cache
def test_recipe_nutrition_unknown_servings():
    from nutrition import recipe_nutrition
    out = recipe_nutrition({"makes": None, "ingredient_groups": [{"items": ["2 eggs"]}]}, cache)
    assert out["servings"] is None and out["per_serving"] is None and out["total"]["protein_g"] > 0


# 9. Kroger sizes -> quantities (unit prices depend on this)
@pytest.mark.parametrize("size, expected", [
    ("16 oz", {"lb": 1.0}),
    ("5 lb", {"lb": 5.0}),
    ("30 ct", {"each": 30}),
    ("4 ct / 15.25 oz", {"each": 4, "lb": pytest.approx(3.81, abs=0.01)}),   # 4 cans x 15.25 oz
    ("", {}),
    ("family size", {}),
])
def test_parse_size(size, expected):
    from browse import parse_size
    assert parse_size(size) == expected


# 10. browse(): price choice, unit price, cheapest per unit first (fake Kroger response, no internet)
def fake_product(pid, name, size, regular, promo=0):
    return {"productId": pid, "description": name, "items": [{"size": size, "price": {"regular": regular, "promo": promo}}]}


def test_browse_sorts_by_unit_price(monkeypatch):
    import browse as b
    monkeypatch.setattr(b, "get_products", lambda h, params: [
        fake_product("1", "Big bag", "5 lb", 3.79),               # $0.76/lb
        fake_product("2", "Small bag", "16 oz", 1.69, promo=1.49),  # sale -> $1.49/lb
        fake_product("3", "Not sold here", "16 oz", 0),            # no price -> dropped
        fake_product("4", "Odd size", "1 bag", 2.00),              # unknown size -> last
    ])
    rows = b.browse({}, "loc", "rice")
    assert [r["name"] for r in rows] == ["Big bag", "Small bag", "Odd size"]
    assert rows[0]["unit_price"] == 0.76 and rows[0]["unit"] == "lb"
    assert rows[1]["best"] == 1.49 and rows[1]["promo"] == 1.49 and rows[1]["regular"] == 1.69
    assert rows[2]["unit_price"] is None


# 11. search_kroger: protein per dollar, and a Kroger failure becomes an error result (not a crash)
def test_search_kroger(tools, monkeypatch):
    def fake_browse(h, loc, term):
        if term == "broken":
            raise RuntimeError("Kroger products failed: HTTP 503")
        return [{"product_id": "P1", "name": "Dry Lentils", "size": "16 oz", "best": 1.50, "promo": None, "unit_price": 1.5, "unit": "lb",
                 "nutrition": {"protein_g": 126, "calories": 2240}},
                {"product_id": "P2", "name": "Mystery Can", "size": "15 oz", "best": 1.00, "promo": None, "unit_price": None, "unit": "lb",
                 "nutrition": None}]
    monkeypatch.setattr(tools, "browse", fake_browse)
    monkeypatch.setattr(tools, "kroger_headers", lambda: {})
    out = tools.search_kroger.func(["lentils", "broken"], {"location_id": "x"})
    assert out["lentils"][0]["protein_per_dollar"] == 84.0               # 126 g / $1.50
    assert out["lentils"][1]["protein_g"] is None and out["lentils"][1]["protein_per_dollar"] is None
    assert out["broken"] == {"error": "Kroger products failed: HTTP 503"}
    assert out["lentils"][0]["id"] == "P1"
    assert tools._products[("x", "P1")]["price"] == 1.50                 # check_budget will read this, by id


# 12. Recipe tools: the right card when two share a title; only cookable cards
def test_recipe_details_picks_real_recipe(tools):
    d = tools.recipe_details.func("Black-Eyed Peas and Collards")
    assert d["page"] == 94 and "1 cup dried black-eyed peas" in d["ingredients"]["ingredients"]
    assert tools.recipe_details.func("No Such Dish") == {"error": "no recipe titled 'No Such Dish'"}


def test_find_recipes_only_cookable(tools):
    found = tools.find_recipes.func("black-eyed peas and collards")
    assert found and all(tools.cookable(next(c for c in tools.cards if c["book_page"] == r["page"] and c["title"] == r["title"]))
                         for r in found)
    assert 73 not in [r["page"] for r in found]                          # the p.73 menu card never shows up


# 13. Kroger token is renewed before it expires (it dies at 30 min; the app runs for hours)
def test_kroger_token_refresh(tools, monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "token", lambda: calls.append(1) or {"Authorization": f"Bearer t{len(calls)}"})
    clock = [1000.0]
    monkeypatch.setattr(tools.time, "time", lambda: clock[0])
    tools._headers.clear()
    assert tools.kroger_headers() == {"Authorization": "Bearer t1"}
    clock[0] += 20 * 60
    assert tools.kroger_headers() == {"Authorization": "Bearer t1"}      # 20 min: reuse
    clock[0] += 6 * 60
    assert tools.kroger_headers() == {"Authorization": "Bearer t2"}      # 26 min: new token
    assert len(calls) == 2
    tools._headers.clear()


# 14. submit_plan: the final JSON plan is checked by code before the student sees it
def plan(tools, recipes, items, **kw):
    return tools.Plan(recipes=[tools.RecipePick(title=t, page=p) for t, p in recipes],
                      items=[tools.Item(id=i, quantity=q) for i, q in items], note="Cheap and warm.", **kw)


def test_submit_plan_accepted(tools):
    out = tools.submit_plan.func(plan(tools, [("Dal", 35)], [("LEN", 2), ("GAR", 1)]), {"location_id": "S1", "budget": 10.0})
    assert out["accepted"] and out["total"] == 5.97 and out["recipes"][0]["page"] == 35
    assert out["recipes"][0]["nutrition"]["per_serving"]["protein_g"] > 0 and out["note"] == "Cheap and warm."


@pytest.mark.parametrize("recipes, items, budget, kw, problem", [
    ([("Dal", 35)], [("LEN", 10)], 10.0, {}, "over the $10.0 budget"),
    ([("Dal", 35)], [("FAKE", 1)], 10.0, {}, "unknown product ids"),
    ([("Dal", 36)], [("LEN", 1)], 10.0, {}, "no cookable recipe 'Dal' on page 36"),             # wrong page
    ([("Black-Eyed Peas and Collards", 73)], [("LEN", 1)], 10.0, {}, "no cookable recipe"),    # menu card
    ([], [("LEN", 1)], 10.0, {}, "no recipes"),
    ([("Black-Eyed Peas and Collards", 94)], [("LEN", 1)], 10.0, {"vegetarian": True}, "not vegetarian"),  # bacon
])
def test_submit_plan_rejected(tools, recipes, items, budget, kw, problem):
    out = tools.submit_plan.func(plan(tools, recipes, items, **kw), {"location_id": "S1", "budget": budget})
    assert out["accepted"] is False and any(problem in p for p in out["problems"])


def test_submit_plan_allergen(tools):
    dal = next(c for c in tools.cards if c["title"] == "Dal" and c["book_page"] == 35)
    allergen = sorted(dal["allergens"])[0]                      # whatever Dal contains (butter -> milk)
    out = tools.submit_plan.func(plan(tools, [("Dal", 35)], [("LEN", 1)], avoid=[allergen]), {"location_id": "S1", "budget": 10.0})
    assert out["accepted"] is False and "breaks the diet" in out["problems"][0]
