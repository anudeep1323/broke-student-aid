"""Recipe nutrition from USDA FoodData Central: code only, no LLM.

For each recipe line ("1 cup dry lentils"): parse amount + unit + food -> USDA food -> grams from USDA's own
portions (1 cup lentils = 192 g) -> grams/100 x nutrients per 100 g. Sum the lines, divide by servings.
Salt, pepper, spices and water count as 0. USDA answers are cached in data/usda_cache.json (reruns are free).
Run: ../.venv/bin/python3 recipes_rag/nutrition.py   -> data/nutrition.json
"""
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from usda_foods import FOODS   # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CACHE = DATA / "usda_cache.json"
load_dotenv(HERE.parent / ".env")
API = "https://api.nal.usda.gov/fdc/v1"
KEYS = {"208": "calories", "203": "protein_g", "205": "carbs_g", "291": "fiber_g", "269": "sugar_g"}  # USDA nutrient numbers

FRACTIONS = {"½": .5, "¼": .25, "¾": .75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": .125}
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "sixteen": 16, "twenty-four": 24, "sixty": 60}
UNITS = {"cup": "cup", "cups": "cup", "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "tsp": "tsp",
         "teaspoon": "tsp", "teaspoons": "tsp", "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb", "oz": "oz",
         "ounce": "oz", "ounces": "oz", "g": "g", "can": "can", "cans": "can", "clove": "clove", "cloves": "clove",
         "slice": "slice", "slices": "slice", "strip": "slice", "strips": "slice", "bunch": "bunch", "pinch": "pinch",
         "large": "large", "medium": "medium", "small": "small", "head": "head", "stalk": "stalk", "stalks": "stalk", "stick": "stalk", "sticks": "stalk", "cob": "ear", "cobs": "ear", "ear": "ear", "ears": "ear"}
GRAMS = {"g": 1, "oz": 28.35, "lb": 453.6, "can": 425}       # weights; a standard can is 15 oz
PER_CUP = {"cup": 1, "tbsp": 1 / 16, "tsp": 1 / 48}           # volumes, all converted through "1 cup = N g"
SKIP = re.compile(r"\b(salt|pepper|peppercorns|spices?|cumin|paprika|oregano|cinnamon|nutmeg|vanilla|turmeric|"
                  r"coriander|chili flakes|chili powder|curry powder|garlic powder|thyme|basil|bay|cayenne|herbs?|"
                  r"dill|cilantro|parsley|sage|mint|rosemary|powder|seeds|star anise|water|baking soda|baking powder|yeast|to taste)\b")


def number(s):
    """'1½' -> 1.5, '1/2' -> 0.5, '3' -> 3, '2-3' -> 2 (first of a range)."""
    s = s.split("-")[0].split("–")[0]
    total = sum(FRACTIONS[ch] for ch in s if ch in FRACTIONS)
    digits = "".join(ch for ch in s if ch not in FRACTIONS)
    if "/" in digits:
        a, b = digits.split("/")
        return total + float(a) / float(b)
    return total + (float(digits) if digits else 0)


def parse(line):
    """'1 cup dry lentils, rinsed' -> (1.0, 'cup', 'dry lentils'); no amount -> None."""
    low = line.lower().replace("(", ",").split(",")[0]
    m = re.match(r"\s*([\d½¼¾⅓⅔⅛/.\-–]+)\s*(.*)", low)
    if not m or not re.search(r"\d|[½¼¾⅓⅔⅛]", m.group(1)):
        return None
    amount, rest = number(m.group(1)), re.sub(r"^(to|or)\s+[\d½¼¾]+\s+", "", m.group(2)).split()
    unit = UNITS.get(rest[0]) if rest else None
    food = " ".join(rest[1:] if unit else rest)
    food = re.split(r"\s+or\s+|\s+instead\b", food)[0].strip()   # "pork shoulder or butt" -> first choice
    return (amount, unit, food) if food else None


def usda(food, cache):
    """Recipe food words -> the hand-checked USDA food (usda_foods.py) -> nutrients per 100 g + portions. Cached.
    No pattern matches -> None (reported as missed, never guessed)."""
    name = next((n for pat, n in FOODS if re.search(pat, food)), None)
    if name is None:
        return None
    if name in cache:
        return cache[name]
    h = {"X-Api-Key": os.environ["FDC_API_KEY"]}
    query = re.sub(r"[^\w ]", " ", name)   # USDA's search 400s on ( ) % /; we still demand the exact name below
    hits = requests.get(f"{API}/foods/search", headers=h, timeout=30,
                        params={"query": query, "dataType": "SR Legacy", "pageSize": 50}).json().get("foods", [])
    exact = next(x for x in hits if x["description"].lower() == name.lower())   # StopIteration = a typo in usda_foods.py
    d = requests.get(f"{API}/food/{exact['fdcId']}", headers=h, timeout=30).json()
    per100 = {KEYS[str(n["nutrient"]["number"])]: n.get("amount", 0) for n in d.get("foodNutrients", [])
              if str(n.get("nutrient", {}).get("number")) in KEYS}
    portions = [{"text": f"{p.get('amount', 1):g} {p.get('modifier') or ''} {(p.get('measureUnit') or {}).get('name', '')}".lower(),
                 "amount": p.get("amount") or 1, "grams": p["gramWeight"]} for p in d.get("foodPortions", [])]
    cache[name] = {"name": d["description"], "per100": per100, "portions": portions}
    return cache[name]


def grams(amount, unit, food):
    """Amount + unit -> grams, using weights, or USDA's own portion for that unit / a whole item."""
    if unit in GRAMS:
        return amount * GRAMS[unit]
    ports = food["portions"]
    if unit in PER_CUP:   # find any cup/tbsp/tsp portion and scale (1 tbsp = 1/16 cup)
        for p in ports:
            for u, f in PER_CUP.items():
                if re.search(rf"\b{u}\b", p["text"]):
                    return amount * PER_CUP[unit] / f * p["grams"] / p["amount"]
        return None
    for want in ([unit] if unit else ["medium", "large", "fruit", "whole"]):   # "4 eggs" = 4 medium eggs
        for p in ports:
            if re.match(rf"[\d.]+ {want}\b", p["text"]):   # word right after the amount: not "1 slice, medium"
                return amount * p["grams"] / p["amount"]
    whole = [p for p in ports if not re.search(r"\b(cup|tbsp|tsp|oz|lb)\b", p["text"])]
    return amount * whole[0]["grams"] / whole[0]["amount"] if whole and unit is None else None


def servings(makes):
    """'for four' -> 4, 'for two, or four as a side' -> 2, 'for four to six' -> 4. Unknown -> None."""
    m = re.search(r"\bfor (\w+)", makes or "")
    return WORDS.get(m.group(1)) if m else None


def recipe_nutrition(card, cache):
    """Whole-recipe totals + per serving (if servings known) + which lines were counted / skipped / missed."""
    total = dict.fromkeys(KEYS.values(), 0.0)
    counted, skipped, missed = [], [], []
    for line in (i for g in card["ingredient_groups"] for i in g["items"]):
        if SKIP.search(line.lower()) and not re.search(r"\b(bell|sweet) pepper", line.lower()):
            skipped.append(line)
            continue
        p = parse(line)
        food = usda(p[2], cache) if p else None
        g = grams(p[0], p[1], food) if food else None
        if g is None:
            missed.append(line)
            continue
        for k, v in food["per100"].items():
            total[k] += g / 100 * v
        counted.append(f"{line} -> {food['name']} {g:.0f} g")
    n = servings(card["makes"])
    out = {"total": {k: round(v) for k, v in total.items()}, "servings": n,
           "per_serving": {k: round(v / n) for k, v in total.items()} if n else None,
           "counted": counted, "skipped": skipped, "missed": missed}
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    from search import cards
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    result = {}
    try:
        for c in cards:
            if c["kind"] == "recipe" and c["ingredient_groups"]:
                result[f"{c['book_page']}|{c['title']}"] = recipe_nutrition(c, cache)
    finally:
        CACHE.write_text(json.dumps(cache, indent=1))   # keep USDA answers even if a run stops halfway
    (DATA / "nutrition.json").write_text(json.dumps(result, indent=1))
    lines = [r for r in result.values()]
    n_c, n_s, n_m = (sum(len(r[k]) for r in lines) for k in ("counted", "skipped", "missed"))
    print(f"{len(result)} recipes | lines: {n_c} counted, {n_s} skipped (spices/salt/water), {n_m} missed")
    print(f"servings known: {sum(1 for r in lines if r['servings'])}/{len(result)} | USDA foods cached: {len(cache)}")
