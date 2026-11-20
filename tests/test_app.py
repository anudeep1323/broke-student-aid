"""The real app.py rendered by Streamlit's test runner, with a saved plan: no Claude, no Kroger (store lookup faked).

Checks that what the student sees comes from the plan's numbers. Run: ../.venv/bin/python3 -m pytest tests/ -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kroger"))
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

PLAN = {
    "accepted": True, "note": "Dal twice is the cheapest protein. Salt isn't priced.",
    "recipes": [{"title": "Dal", "page": 35, "photo_id": None, "batches": 2, "allergens": ["milk"], "vegetarian": "yes",
                 "nutrition": {"per_serving": {"calories": 381, "protein_g": 24, "carbs_g": 65, "fiber_g": 11, "sugar_g": 4},
                               "servings": 4, "per": "serving"}}],
    "lines": [{"id": "1", "name": "Dry Lentils", "size": "16 oz", "price": 1.49, "quantity": 4, "line_total": 5.96, "protein_g": 504},
              {"id": "2", "name": "Garlic", "size": "6 oz", "price": 2.99, "quantity": 1, "line_total": 2.99, "protein_g": None}],
    "total": 8.95, "budget": 25.0, "left": 16.05, "within_budget": True, "no_label": ["Garlic"],
    "nutrition_week": {"calories": 8960, "protein_g": 504, "carbs_g": 1624, "fiber_g": 280, "sugar_g": 56}, "protein_g_per_day": 72,
    "eaten_week": {"calories": 3048, "protein_g": 192, "carbs_g": 520, "fiber_g": 88, "sugar_g": 32},
    "eaten_per_day": {"calories": 435, "protein_g": 27, "carbs_g": 74, "fiber_g": 13, "sugar_g": 5},
    "servings_planned": 8, "protein_goal_g_per_day": 60,
    "meals": ["dinner"], "meals_target": 7, "meals_planned": 8, "budget_limited": False,
    "calendar": {d: {"dinner": "Dal"} for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}, "goal_met": False, "protein_short_g_per_day": 33,
}


@pytest.fixture
def app(monkeypatch):
    import browse
    monkeypatch.setattr(browse, "token", lambda: {})
    monkeypatch.setattr(browse, "nearest_store", lambda h, z: ("STORE1", "Test Kroger, 1 Main St"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value("45202").run()
    return at


def test_needs_a_zip():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert "5-digit ZIP" in at.sidebar.info[0].value


def test_store_shown(app):
    assert any("Test Kroger" in c.value for c in app.sidebar.caption)


def test_plan_view_numbers_come_from_the_plan(app):
    app.session_state["chat"] = [("user", "cheap protein", [], "", None), ("assistant", PLAN["note"], PLAN["recipes"], "", PLAN)]
    app.run()
    tiles = {m.label: m.value for m in app.metric}
    assert tiles["🛒 Total"] == "$8.95"
    assert tiles["💪 Protein eaten / day (goal 60 g)"] == "27 g"           # eaten (recipes x batches), not bought (72)
    assert tiles["🍳 Meals covered"] == "8 of 7"
    week = app.dataframe[0].value
    assert list(week.columns) == ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] and week.iloc[0]["Sun"] == "Dal"
    assert tiles["🔥 kcal eaten / day"] == "435"
    table = app.dataframe[1].value
    assert list(table["Product"]) == ["Dry Lentils", "Garlic"] and list(table["Line total"]) == [5.96, 2.99]
    assert any("Dal twice" in m.value for m in app.markdown)               # Claude's note is shown
    assert any("View recipe" in b.label for b in app.button)               # recipe card with its button


def test_no_plan_shows_text_only(app):
    app.session_state["chat"] = [("user", "x", [], "", None), ("assistant", "Kroger is down, no prices.", [], "", None)]
    app.run()
    assert not app.metric and any("Kroger is down" in m.value for m in app.markdown)
