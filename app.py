"""Broke Student Aid: sidebar fields (ZIP, budget) + 'Ask' tab (the agent, in plain English) + 'Browse' tab (search + basket).

Run: python3 -m streamlit run app.py
"""
import json
import re
import sys
import time
from pathlib import Path

import streamlit as st
from langchain_core.messages import HumanMessage, ToolMessage

ROOT = Path(__file__).resolve().parent
for folder in ("kroger", "grocery", "agent", "recipes_rag"):
    sys.path.insert(0, str(ROOT / folder))
from browse import browse, nearest_store, token   # noqa: E402
from match import load_recipes, rank            # noqa: E402
IMAGES = ROOT / "recipes_rag" / "data" / "images"

st.set_page_config(page_title="Broke Student Aid", page_icon="🛒", layout="wide")
D = "\\$"   # escaped dollar: Streamlit reads text between two $ signs as a math formula
money = lambda text: text.replace("$", D)   # escape every $ in text Claude wrote


@st.cache_resource(ttl=1500)   # Kroger tokens last 30 min; reuse one for 25 min instead of 1 call per search
def kroger_headers():
    """One Kroger app token shared by every search."""
    return token()


@st.cache_data(ttl=86400)      # a ZIP's nearest store doesn't change during the day
def store_for(zip_code):
    """Nearest Kroger to a ZIP: (locationId, name)."""
    return nearest_store(kroger_headers(), zip_code)


@st.cache_resource             # 95 recipe cards + their grocery names, loaded once
def recipes():
    """All recipe cards with plain ingredient names (grocery/match.py)."""
    return load_recipes()


@st.cache_data(ttl=3600)       # same word at the same store within an hour = no new API call
def products(location_id, term):
    """Real products for one search word, cheapest per unit first."""
    return browse(kroger_headers(), location_id, term)


@st.cache_resource             # the agent: loads the search model + cards once (~10 s), then reused
def agent():
    """The LangGraph app (Haiku gathers, Sonnet decides + writes) and its price table."""
    from graph import PRICES, app
    return app, PRICES


def final_plan(out):
    """The accepted, code-checked plan from graph.py (same function the eval uses)."""
    from graph import final_plan as fp
    return fp(out)


def full_card(title, page):
    """The whole saved recipe card (ingredients, steps, nutrition) for a title + page. No LLM: read from disk."""
    from search import cards   # loaded once by the agent's tools
    return next((c for c in cards if c["title"] == title and c["book_page"] == page), None)


@st.dialog("Recipe", width="large")
def show_recipe(title, page):
    """Pop-up with everything about one recipe: big photo, nutrition, ingredients, steps."""
    c = full_card(title, page)
    if c is None:
        st.error("Recipe card not found.")
        return
    st.subheader(f"{c['title']}  ·  Good and Cheap p.{c['book_page']}")
    photo_col, facts_col = st.columns([2, 3])   # photo beside the numbers, so the recipe is visible without scrolling
    photo = IMAGES / f"{c['photo_id']}.png" if c.get("photo_id") else None
    if photo and photo.exists():
        photo_col.image(str(photo), width="stretch")
    n = c.get("nutrition")
    if n:
        per = n.get("per_serving") or n.get("whole_recipe")
        unit = n.get("per", "serving")
        label = (f"per {unit} (makes {n['servings']:g} {unit}s)" if n.get("per_serving")
                 else "whole recipe (servings unknown)")
        facts_col.caption(f"Nutrition {label}, from USDA data")
        top, bottom = facts_col.columns(3), facts_col.columns(3)
        for col, (k, name) in zip(top + bottom, [("calories", "kcal"), ("protein_g", "protein g"), ("carbs_g", "carbs g"),
                                                  ("fiber_g", "fiber g"), ("sugar_g", "sugar g")]):
            col.metric(name, per[k])
    left, right = st.columns([2, 3])
    with left:
        st.markdown("**Ingredients**" + (f" ({c['makes']})" if c.get("makes") else ""))
        for g in c["ingredient_groups"]:
            if g.get("name"):
                st.markdown(f"*{g['name']}*")
            st.markdown("\n".join(f"- {money(i)}" for i in g["items"]))
    with right:
        st.markdown("**How to make it**")
        st.markdown(money(c["steps"]))


def recipe_cards(recs, key):
    """One card per recommended recipe: photo, title, protein, and a button that opens the full recipe."""
    cols = st.columns(len(recs))
    for col, c in zip(cols, recs):
        with col.container(border=True):
            photo = IMAGES / f"{c['photo_id']}.png" if c.get("photo_id") else None
            if photo and photo.exists():
                st.image(str(photo), width="stretch")
            st.markdown(f"**{c['title']}** · p.{c['page']}")
            per = (c.get("nutrition") or {}).get("per_serving")
            if per:
                st.caption(f"{per['calories']} kcal · {per['protein_g']} g protein per {c['nutrition'].get('per', 'serving')}")
            if st.button("📖 View recipe", key=f"{key}-{c['page']}-{c['title']}", width="stretch"):
                show_recipe(c["title"], c["page"])


def plan_view(plan, key):
    """One accepted plan at a glance. Every number comes from code (submit_plan); only the note is Claude's words."""
    st.markdown(money(plan["note"]))
    a, c2 = st.columns(2)   # 2 x 2 tiles: 4 in a row cut off the numbers in a narrow window
    c3, c4 = st.columns(2)
    a.metric("🛒 Total", f"${plan['total']:.2f}", f"${plan['left']:.2f} left", border=True)   # code refuses over-budget plans
    goal, day = plan.get("protein_goal_g_per_day"), plan["eaten_per_day"]   # from recipes x batches: what you eat
    c2.metric(f"💪 Protein eaten / day" + (f" (goal {goal} g)" if goal else ""), f"{day['protein_g']} g",
              (("goal met" if plan.get("goal_met") else f"-{plan['protein_short_g_per_day']} g") if goal else None), border=True)
    c3.metric("🍳 Meals covered", f"{plan['meals_planned']} of {plan['meals_target']}",
              "budget ran out" if plan.get("budget_limited") else ", ".join(f"{r['title']} ×{r['batches']}" for r in plan["recipes"]),
              delta_color="inverse" if plan.get("budget_limited") else "off", border=True)
    c4.metric("🔥 kcal eaten / day", f"{day['calories']:,}",
              f"carbs {day['carbs_g']} g · fiber {day['fiber_g']} g · sugar {day['sugar_g']} g", delta_color="off", border=True)
    st.markdown("**🗓️ Your week**")
    st.dataframe([{"": m.title(), **{d: plan["calendar"][d][m] or "–" for d in plan["calendar"]}} for m in plan["meals"]],
                 hide_index=True, width="stretch")
    recipe_cards(plan["recipes"], key=key)
    st.markdown("**🧾 Shopping list**")
    st.dataframe([{"Product": l["name"], "Size": l["size"], "Qty": l["quantity"], "Price": l["price"],
                   "Line total": l["line_total"], "Protein (g)": l["protein_g"] if l["protein_g"] is not None else "–"}
                  for l in plan["lines"]], hide_index=True, width="stretch",
                 column_config={"Price": st.column_config.NumberColumn(format="$%.2f"),
                                "Line total": st.column_config.NumberColumn(format="$%.2f")})
    st.caption(f"Groceries hold {plan['protein_g_per_day']} g protein/day from Kroger labels (leftovers included); "
               "the tiles count only what the recipes use." + (" No label: " + ", ".join(plan["no_label"]) if plan.get("no_label") else ""))
    with st.expander("🧩 The plan as JSON (what code checked)"):
        st.json({k: v for k, v in plan.items() if k != "note"}, expanded=False)


def cost_of(out, prices):
    """$ for every Claude call in one answer (cache reads priced separately)."""
    total = 0
    for m in out["messages"] + out["plan_messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            p_in, p_out, p_read = next(v for k, v in prices.items() if m.response_metadata.get("model_name", "").startswith(k))
            read = (u.get("input_token_details", {}) or {}).get("cache_read", 0) or 0
            total += ((u["input_tokens"] - read) * p_in + read * p_read + u["output_tokens"] * p_out) / 1e6
    return total


def product_row(r, term, basket):
    """One product with a checkbox: ticked = in the basket."""
    per = f"{D}{r['unit_price']}/{r['unit']}" if r["unit_price"] else "size?"
    sale = f" 🏷️ sale (reg {D}{r['regular']})" if r["promo"] else ""
    label = f"**{D}{r['best']:.2f}** · {r['name']} · {r['size']} · {per}{sale}"
    if st.checkbox(label, value=r["product_id"] in basket, key=f"{term}-{r['product_id']}"):
        basket[r["product_id"]] = r
    else:
        basket.pop(r["product_id"], None)


# Sidebar: the fields that must never be guessed (checked by code)
with st.sidebar:
    st.title("🛒 Broke Student Aid")
    zip_code = st.text_input("ZIP code", max_chars=5, placeholder="45202")
    budget = st.number_input("Weekly budget ($)", min_value=0.0, value=25.0, step=5.0)
    protein_goal = st.slider("💪 Protein goal (g per day)", 0, 150, 0, step=10,
                             help="0 = no goal. Otherwise the plan favours protein per dollar (Kroger labels) and code checks the goal.")
    if not re.fullmatch(r"\d{5}", zip_code or ""):
        st.info("Enter a 5-digit ZIP code to find your nearest Kroger.")
        st.stop()
    try:
        location_id, store_name = store_for(zip_code)
    except (IndexError, KeyError):
        st.error(f"No Kroger store found near {zip_code}.")
        st.stop()
    st.caption(f"📍 {store_name}")
    st.caption("Recipes from *Good and Cheap* by Leanne Brown (CC BY-NC-SA).")

ask_tab, browse_tab = st.tabs(["💬 Ask", "🔎 Browse Kroger"])

# Tab 1: the agent
with ask_tab:
    history = st.session_state.setdefault("chat", [])   # [(role, text, recipes, how, plan)]
    for n, (role, text, recs, how, *rest) in enumerate(history):
        with st.chat_message(role):
            if role == "assistant" and rest and rest[0] and "note" in rest[0]:
                plan_view(rest[0], key=f"msg{n}")
            else:
                st.markdown(money(text))
                if recs:
                    recipe_cards(recs, key=f"msg{n}")
            if how:
                with st.expander("🔍 How I got this"):
                    st.markdown(money(how))
    sentence = st.chat_input("e.g. I'm broke till Friday, no peanuts, tired of rice, want something warm")
    if sentence:
        history.append(("user", sentence, [], "", None))
        with st.spinner("Checking the cookbook and your Kroger's prices... (~30 s)"):
            app, prices = agent()
            t0 = time.time()
            out = app.invoke({"messages": [HumanMessage(sentence)], "plan_messages": [], "location_id": location_id,
                              "budget": float(budget), "tool_calls": [], "protein_goal": protein_goal})
            secs = time.time() - t0
        how = (f"{len(out['tool_calls'])} tool calls, ${cost_of(out, prices):.3f}, {secs:.0f} s\n\n"
               + "\n".join(f"- `{c[:120]}`" for c in out["tool_calls"]))
        plan = final_plan(out)
        if plan:   # the normal case: one accepted, code-checked plan
            history.append(("assistant", plan["note"], plan["recipes"], how, plan))
        else:      # no accepted plan (e.g. Kroger down): show Claude's explanation, no numbers
            history.append(("assistant", out["plan_messages"][-1].text or "Sorry, I couldn't build a plan.", [], how, None))
        st.rerun()

# Tab 2: browse + basket (screen 1)
with browse_tab:
    STAPLES = {"🍚 rice": "rice", "🥚 eggs": "eggs", "🫘 black beans": "black beans", "🟤 lentils": "lentils",
               "🍝 pasta": "pasta", "🥔 potatoes": "potatoes", "🧅 onions": "onions", "🥛 milk": "milk",
               "🍞 bread": "bread", "🥜 peanut butter": "peanut butter"}
    picked = st.pills("Quick picks: cheap staples", list(STAPLES), selection_mode="multi")   # one click = one search
    typed = st.text_input("Or type anything (comma-separated, then Enter)", placeholder="e.g. tofu, frozen spinach")
    basket = st.session_state.setdefault("basket", {})          # product_id -> product row
    wanted = [STAPLES[p] for p in picked] + [x.strip() for x in typed.split(",") if x.strip()]
    if not wanted:
        st.caption("👆 Pick a staple or type a food to see real prices at your Kroger.")
    for term in dict.fromkeys(wanted):                           # keep order, drop repeats
        rows = products(location_id, term)
        if not rows:
            st.caption(f"No products found for “{term}”.")
            continue
        with st.container(border=True):   # one group per food: best value up front, the rest one click away
            st.markdown(f"**{term.title()}** · {len(rows)} options · from {D}{min(r['best'] for r in rows):.2f}")
            st.caption("⭐ Best value (cheapest per unit)")
            product_row(rows[0], term, basket)
            if len(rows) > 1:
                with st.expander(f"See {len(rows) - 1} more sizes and brands"):
                    for r in rows[1:]:
                        product_row(r, term, basket)
    st.divider()
    total = sum(r["best"] for r in basket.values())
    left = budget - total
    st.subheader(f"🧺 Basket: {len(basket)} items · {D}{total:.2f} of {D}{budget:.2f}")
    st.progress(min(total / budget, 1.0) if budget else 0.0)
    (st.success if left >= 0 else st.error)(f"{D}{left:.2f} left" if left >= 0 else f"{D}{-left:.2f} over budget")
    if basket:
        st.subheader("🍳 Recipes you can make with your basket")
        for r in rank([b["name"] for b in basket.values()], recipes()):
            c = r["card"]
            left_col, right_col = st.columns([1, 3])
            photo = IMAGES / f"{c['photo_id']}.png" if c["photo_id"] else None
            if photo and photo.exists():
                left_col.image(str(photo), width="stretch")
            right_col.markdown(f"**{c['title']}** · Good and Cheap p.{c['book_page']}")
            right_col.write(f"✅ You have: {', '.join(r['have'])}  ·  🛒 Still need: {', '.join(r['missing']) or 'nothing!'}")
