"""Stage 3: hybrid recipe search over the JSON cards.

BM25 = exact words ("tofu"), MiniLM vectors = meaning ("warm" ~ soup, stew),
fused with Reciprocal Rank Fusion (RRF). Diet rules (allergens, vegetarian) remove cards BEFORE ranking.
Usage: python3 -I recipes_rag/search.py "something warm with tofu"
"""
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diet import allergens, vegetarian   # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
RRF_K, TOP_K = 60, 3


def load_cards():
    """Load every card file and keep only food cards (no sections, tips or about pages)."""
    cards = []
    for f in sorted(glob.glob(str(DATA / "cards" / "pdf*_haiku.json"))):
        cards += [c for c in json.load(open(f)) if c["kind"] != "section" and c["category"] not in ("tip", "about")]  # food only
    TITLE_FIXES = {(101, "And Mine"): "Baked Beans from Scratch"}   # p.101 heading only makes sense after p.100
    facts = json.loads((DATA / "nutrition.json").read_text()) if (DATA / "nutrition.json").exists() else {}
    for c in cards:   # USDA nutrition computed by code (nutrition.py): per serving if servings known, else whole recipe
        c["title"] = TITLE_FIXES.get((c["book_page"], c["title"]), c["title"])   # fix first: every file sees one title
        n = facts.get(f"{c['book_page']}|{c['title']}")
        c["nutrition"] = None if n is None else (
            {"per_serving": n["per_serving"], "servings": n["servings"], "per": n.get("serving_unit") or "serving"}
            if n["per_serving"]
            else {"servings": "unknown"}) | {"whole_recipe": n["total"], "lines_not_counted": len(n["missed"])}
            # whole_recipe always there: one batch's totals, used to count what the student eats (x batches)
    return cards


def card_text(c):
    """Build the one sentence we embed for a card: [Category] title + ingredients + start of steps.
    Prices, page and photo stay as exact fields, never embedded."""
    items = "; ".join(i for g in c["ingredient_groups"] for i in g["items"])
    return f"[{c['category'].replace('_', ' ').title()}] {c['title']}. Ingredients: {items}. {c['steps'][:300]}"


def tokens(s):
    """Split text into lowercase words for BM25 ('Tofu Hot-Pot!' -> ['tofu', 'hot', 'pot'])."""
    return re.findall(r"[a-z]+", s.lower())


cards = load_cards()
by_page = defaultdict(list)                                # book page -> recipes, to follow "(p. 164)"
for c in cards:
    if c["kind"] == "recipe":
        by_page[c["book_page"]].append(c)
for c in cards:                                            # diet fields: worked out by code, never stored
    c["allergens"], c["vegetarian"] = allergens(c, by_page), vegetarian(c)
    c["has_ingredients"] = any(g["items"] for g in c["ingredient_groups"])
texts = [card_text(c) for c in cards]
bm25 = BM25Okapi([tokens(t) for t in texts])
model = SentenceTransformer("all-MiniLM-L6-v2")             # local, 384-dim, no API key
vectors = model.encode(texts, normalize_embeddings=True)    # one vector per card


def allowed(c, avoid, veg):
    """Diet filter: drop cards with an avoided allergen, meat for vegetarians, and idea cards with no
    ingredient list when any allergy is set (we can't prove they're safe)."""
    if veg and c["vegetarian"] == "no":
        return False
    if avoid and (not c["has_ingredients"] or c["allergens"] & avoid):
        return False
    return True


def search(query, k=TOP_K, avoid=frozenset(), vegetarian=False):
    """Remove cards that break the diet rules, then rank the rest by words (BM25) and meaning (vectors),
    merge with RRF, return the top k as (card, rank by words, rank by meaning)."""
    ok = {i for i, c in enumerate(cards) if allowed(c, set(avoid), vegetarian)}
    by_words = [i for i in np.argsort(-bm25.get_scores(tokens(query))) if i in ok]
    by_meaning = [i for i in np.argsort(-(vectors @ model.encode([query], normalize_embeddings=True)[0])) if i in ok]
    fused = {}
    for ranking in (by_words, by_meaning):                  # RRF: 1/(60 + rank), summed
        for rank, i in enumerate(ranking[:20]):
            fused[i] = fused.get(i, 0) + 1 / (RRF_K + rank + 1)
    best = sorted(fused, key=fused.get, reverse=True)[:k]
    return [(cards[i], by_words.index(i) + 1, by_meaning.index(i) + 1) for i in best]


if __name__ == "__main__":
    for q in sys.argv[1:]:
        print(f'\n"{q}"  ({len(cards)} cards)')
        for c, rw, rm in search(q):
            price = f"${c['unit_cost']}/{c['cost_unit']}" if c["unit_cost"] is not None else "no price"
            print(f"  p.{c['book_page']:<4} {c['title'][:38]:38} {price:15} photo {c['photo_id']}"
                  f"  | words #{rw}, meaning #{rm}")
