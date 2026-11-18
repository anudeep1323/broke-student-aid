"""Allergen + vegetarian eval: diet.py vs 22 hand-labelled cards ($0, no LLM).

Safety score = allergen RECALL (missed allergens are dangerous). Extra warnings only cost precision.
Usage: python3 -I recipes_rag/evals/eval_diet.py
"""
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from diet import allergens, vegetarian   # noqa: E402

cards = [c for f in sorted(glob.glob(str(HERE.parent / "data" / "cards" / "pdf*_haiku.json"))) for c in json.load(open(f))]
by_page = defaultdict(list)                # book page -> recipe cards on it (to follow "(p. 164)")
for c in cards:
    if c["kind"] == "recipe":
        by_page[c["book_page"]].append(c)
gold = json.load(open(HERE / "gold_diet.json"))

caught = true = flagged = veg_ok = 0
missed, extra, veg_wrong = [], [], []
for g in gold["cards"]:
    card = next(c for c in cards if c["title"] == g["title"] and g.get("book_page", c["book_page"]) == c["book_page"])
    got, want = allergens(card, by_page), set(g["allergens"])
    caught += len(got & want); true += len(want); flagged += len(got)
    missed += [f"{g['title']}: MISSED {a}" for a in sorted(want - got)]
    extra += [f"{g['title']}: extra {a}" for a in sorted(got - want)]
    v = vegetarian(card)
    veg_ok += v == g["vegetarian"]
    if v != g["vegetarian"]:
        veg_wrong.append(f"{g['title']}: vegetarian gold {g['vegetarian']} got {v}  (trap: {g['trap']})")

print(f"{len(gold['cards'])} hand-labelled cards")
print(f"allergen RECALL {caught}/{true} = {caught / true:.0%}   <- safety: must be 100%")
print(f"allergen precision {caught}/{flagged} = {caught / flagged:.0%}   (extra warnings)")
print(f"vegetarian {veg_ok}/{len(gold['cards'])}")
for line in missed + veg_wrong + extra:
    print("  -", line)
food = [c for c in cards if c["kind"] != "section" and c["category"] not in ("tip", "about")]
counts = Counter(a for c in food for a in allergens(c, by_page))
print(f"\nall {len(food)} food cards: " + ", ".join(f"{a} {n}" for a, n in counts.most_common())
      + f" | vegetarian: {dict(Counter(vegetarian(c) for c in food))}")
