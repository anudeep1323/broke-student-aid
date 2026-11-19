"""Broke Student Aid, screen 1: ZIP + budget -> search real Kroger products -> tick into a basket -> total vs budget
-> recipes from the cookbook that use the basket (with photos).

Run: python3 -m streamlit run app.py
"""
import re
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "kroger"))
sys.path.insert(0, str(ROOT / "grocery"))
from browse import browse, nearest_store, token   # noqa: E402
from match import load_recipes, rank            # noqa: E402
IMAGES = ROOT / "recipes_rag" / "data" / "images"

st.set_page_config(page_title="Broke Student Aid", page_icon="🛒")
D = "\\$"   # escaped dollar: Streamlit reads text between two $ signs as a math formula
st.title("🛒 Broke Student Aid")


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


# 1. Dedicated inputs, checked by code (no chat, no LLM)
col1, col2 = st.columns(2)
zip_code = col1.text_input("ZIP code", max_chars=5, placeholder="45202")
budget = col2.number_input("Weekly budget ($)", min_value=0.0, value=30.0, step=5.0)
if not re.fullmatch(r"\d{5}", zip_code or ""):
    st.info("Enter a 5-digit ZIP code to find your nearest Kroger.")
    st.stop()
try:
    location_id, store_name = store_for(zip_code)
except (IndexError, KeyError):
    st.error(f"No Kroger store found near {zip_code}.")
    st.stop()
st.caption(f"📍 Nearest Kroger: {store_name}")

# 2. Search real products
terms = st.text_input("Search food (comma-separated)", placeholder="rice, eggs, black beans")
basket = st.session_state.setdefault("basket", {})          # product_id -> product row
for term in [t.strip() for t in terms.split(",") if t.strip()]:
    rows = products(location_id, term)
    st.subheader(f"{term}  ·  {len(rows)} products, cheapest per unit first")
    for r in rows:
        per = f"{D}{r['unit_price']}/{r['unit']}" if r["unit_price"] else "size?"
        sale = f" 🏷️ sale (reg {D}{r['regular']})" if r["promo"] else ""
        label = f"**{D}{r['best']:.2f}** · {r['name']} · {r['size']} · {per}{sale}"
        if st.checkbox(label, value=r["product_id"] in basket, key=f"{term}-{r['product_id']}"):
            basket[r["product_id"]] = r
        else:
            basket.pop(r["product_id"], None)

# 3. Basket total vs budget
st.divider()
total = sum(r["best"] for r in basket.values())
left = budget - total
st.subheader(f"🧺 Basket: {len(basket)} items · {D}{total:.2f} of {D}{budget:.2f}")
st.progress(min(total / budget, 1.0) if budget else 0.0)
(st.success if left >= 0 else st.error)(f"{D}{left:.2f} left" if left >= 0 else f"{D}{-left:.2f} over budget")
for r in basket.values():
    st.write(f"- {D}{r['best']:.2f} · {r['name']} ({r['size']})")

# 4. Recipes from the cookbook that use the basket
if basket:
    st.divider()
    st.subheader("🍳 Recipes you can make with your basket")
    for r in rank([b["name"] for b in basket.values()], recipes()):
        c = r["card"]
        left_col, right_col = st.columns([1, 2])
        photo = IMAGES / f"{c['photo_id']}.png" if c["photo_id"] else None
        if photo and photo.exists():
            left_col.image(str(photo), width="stretch")
        cost = f" · book price {D}{c['unit_cost']}/{c['cost_unit']}" if c["unit_cost"] is not None else ""
        right_col.markdown(f"**{c['title']}** · Good and Cheap p.{c['book_page']}{cost}")
        right_col.write(f"✅ You have: {', '.join(r['have'])}")
        right_col.write(f"🛒 Still need: {', '.join(r['missing']) or 'nothing!'}")
