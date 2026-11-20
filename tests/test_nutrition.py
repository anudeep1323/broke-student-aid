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
@pytest.mark.parametrize("makes, n", [
    ("for four", 4), ("for two, or four as a side", 2), ("for four to six", 4), ("twelve", None), (None, None),
])
def test_servings(makes, n):
    assert servings(makes) == n


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


# 6. Budget + nutrition math in check_budget (code, not the AI)
@pytest.fixture
def tools():
    pytest.importorskip("langgraph")
    import tools
    tools._labels.clear()
    tools._labels.update({"lentils 16 oz": {"protein_g": 126, "calories": 2240, "carbs_g": 406, "fiber_g": 70, "sugar_g": 14},
                          "beans 15 oz": {"protein_g": 21, "calories": 385, "carbs_g": 70, "fiber_g": 21, "sugar_g": 0}})
    return tools


def test_check_budget_math(tools):
    out = tools.check_budget.func(
        [tools.Item(name="Lentils 16 oz", price=1.49, quantity=2), tools.Item(name="Beans 15 oz", price=1.09, quantity=2),
         tools.Item(name="Garlic", price=2.99)],
        {"budget": 10.0, "protein_goal": 80})
    assert [l["line_total"] for l in out["lines"]] == [2.98, 2.18, 2.99]   # 1.09 x 2 = 2.18
    assert out["total"] == 8.15 and out["left"] == 1.85 and out["within_budget"]
    assert out["nutrition_week"]["protein_g"] == 126 * 2 + 21 * 2          # 294 g
    assert out["protein_g_per_day"] == 42                                 # 294 / 7
    assert out["no_label"] == ["Garlic"]
    assert out["goal_met"] is False and out["protein_short_g_per_day"] == 38


def test_over_budget(tools):
    out = tools.check_budget.func([tools.Item(name="Lentils 16 oz", price=1.49, quantity=10)], {"budget": 10.0})
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
        return [{"name": "Dry Lentils", "size": "16 oz", "best": 1.50, "promo": None, "unit_price": 1.5, "unit": "lb",
                 "nutrition": {"protein_g": 126, "calories": 2240}},
                {"name": "Mystery Can", "size": "15 oz", "best": 1.00, "promo": None, "unit_price": None, "unit": "lb",
                 "nutrition": None}]
    monkeypatch.setattr(tools, "browse", fake_browse)
    monkeypatch.setattr(tools, "kroger_headers", lambda: {})
    out = tools.search_kroger.func(["lentils", "broken"], {"location_id": "x"})
    assert out["lentils"][0]["protein_per_dollar"] == 84.0               # 126 g / $1.50
    assert out["lentils"][1]["protein_g"] is None and out["lentils"][1]["protein_per_dollar"] is None
    assert out["broken"] == {"error": "Kroger products failed: HTTP 503"}
    assert tools._labels["dry lentils"]["protein_g"] == 126               # check_budget will read this


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
