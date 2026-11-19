"""Basket -> recipes: which recipe cards use the Kroger products the student ticked, and what's still missing. Code only, $0.

Usage: python3 -I grocery/match.py "Kroger® Long Grain Rice" "Kroger® Medium Grade A White Eggs"
"""
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingredients import CARDS, normalise   # noqa: E402


def words(text):
    """Lowercase words with simple plurals removed: 'White Eggs' -> {'white', 'egg'}."""
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        out.add(w[:-2] if w.endswith("oes") else w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
    return out


def load_recipes():
    """Every recipe card with its plain grocery names: [(card, {names})]."""
    out = []
    for f in sorted(glob.glob(str(CARDS / "pdf*_haiku.json"))):
        for c in json.load(open(f)):
            if c["kind"] == "recipe":
                names = {normalise(i) for g in c["ingredient_groups"] for i in g["items"]} - {None}
                if names:
                    out.append((c, names))
    return out


def covers(product_name, ingredient):
    """A product covers an ingredient if every word of the ingredient is in the product name
    ('rice' in 'Kroger Long Grain Rice'; 'olive oil' not in 'Vegetable Oil')."""
    return words(ingredient) <= words(product_name)


def rank(basket_names, recipes, k=5):
    """Recipes that use the basket: most basket products used first, then highest share of ingredients covered."""
    results = []
    for card, names in recipes:
        have = {n for n in names if any(covers(p, n) for p in basket_names)}
        used = {p for p in basket_names if any(covers(p, n) for n in names)}
        if have:
            results.append({"card": card, "have": sorted(have), "missing": sorted(names - have), "used": len(used),
                            "share": len(have) / len(names)})
    return sorted(results, key=lambda r: (-r["used"], -r["share"]))[:k]


if __name__ == "__main__":
    recipes = load_recipes()
    print(f"basket: {sys.argv[1:]}\n{len(recipes)} recipes checked")
    for r in rank(sys.argv[1:], recipes):
        c = r["card"]
        print(f"  {c['title'][:34]:34} p.{c['book_page']:<4} uses {r['used']} basket item(s), "
              f"{len(r['have'])}/{len(r['have']) + len(r['missing'])} ingredients | have {r['have']} | missing {r['missing'][:5]}")
