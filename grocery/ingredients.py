"""Grocery piece 1: turn messy recipe lines into plain grocery names, by code ($0).

"2 cloves garlic, finely chopped" -> "garlic";  "½ to 1 cup coconut milk" -> "coconut milk".
Usage: python3 -I grocery/ingredients.py      (prints the most common ingredients across all recipes)
"""
import glob
import json
import re
from collections import Counter
from pathlib import Path

CARDS = Path(__file__).resolve().parent.parent / "recipes_rag" / "data" / "cards"
UNITS = (r"cups?|tbsp|tsp|tablespoons?|teaspoons?|lbs?|pounds?|oz|ounces?|cans?|cloves?|bunch(?:es)?|heads?|pinch|"
         r"handfuls?|sticks?|slices?|pieces?|fillets?|packages?|large|medium|small|whole|dried|fresh|freshly|frozen|canned")
PREP = r"\b(?:finely|roughly|thinly|chopped|diced|minced|grated|sliced|crumbled|cubed|peeled|melted|shredded|toasted|cooked|raw)\b"
BASICS = {"salt", "pepper", "salt and pepper", "water", "black pepper", "ice"}   # assume every student has these


def normalise(line):
    """One recipe line -> a plain grocery name, or None for basics / empty lines."""
    s = line.lower()
    s = re.sub(r"\(.*?\)", " ", s)                      # drop "(optional)", "(p. 122)"
    s = s.split(",")[0]                                  # "garlic, finely chopped" -> "garlic"
    if " or " in s:                                      # "2 large or 4 medium potatoes": first alternative that names a food
        return next((n for n in map(normalise, s.split(" or ")) if n), None)
    s = re.sub(r"[\d½¼¾⅓⅔⅛/.\-]+", " ", s)               # quantities: 2, ½, 1/2, 1-2
    s = re.sub(rf"\b(?:to|of|a|an)\b|\b(?:{UNITS})\b|{PREP}", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s or s in BASICS:
        return None
    if s.endswith("oes"):                                # potatoes -> potato
        s = s[:-2]
    elif s.endswith("s") and not s.endswith(("ss", "us")):   # eggs -> egg, onions -> onion
        s = s[:-1]
    return s


def recipe_ingredients():
    """{recipe title: set of grocery names} for every recipe card."""
    out = {}
    for f in sorted(glob.glob(str(CARDS / "pdf*_haiku.json"))):
        for c in json.load(open(f)):
            if c["kind"] == "recipe":
                names = {normalise(i) for g in c["ingredient_groups"] for i in g["items"]}
                out[f"{c['title']} (p.{c['book_page']})"] = names - {None}
    return out


if __name__ == "__main__":
    recipes = recipe_ingredients()
    counts = Counter(n for names in recipes.values() for n in names)
    print(f"{len(recipes)} recipes, {len(counts)} distinct grocery names after normalising")
    print("top 40 (name: how many recipes use it):")
    print(", ".join(f"{n}: {k}" for n, k in counts.most_common(40)))
    for line in ["2 cloves garlic, finely chopped", "½ to 1 cup coconut milk", "1 cup peas, fresh or frozen",
                 "butter or vegetable oil", "2 large or 4 medium potatoes, chopped", "salt and pepper"]:
        print(f"  {line!r:42} -> {normalise(line)!r}")
