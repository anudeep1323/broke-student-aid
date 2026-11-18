"""Rules eval: questions with diet rules. Checks (1) the rules were read, (2) ZERO top-3 results break them.

Usage: python3 -I recipes_rag/evals/eval_rules.py      (8 Haiku rewrites, ~$0.001)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from rewrite import LM, rewrite   # noqa: E402
from search import search         # noqa: E402

CASES = [  # (question, allergens that must be avoided, vegetarian?)
    ("something warm, I'm allergic to soy", {"soy"}, False),
    ("nut allergy, I need a sauce for noodles", {"peanut", "tree_nut"}, False),
    ("dairy-free dessert", {"milk"}, False),
    ("gluten free breakfast", {"wheat"}, False),
    ("cheap vegetarian dinner", set(), True),
    ("vegetarian, no peanuts, something quick and warm", {"peanut"}, True),
    ("I can't eat shellfish, something with rice", {"shellfish"}, False),
    ("egg-free baking, muffins or cookies", {"egg"}, False),
]

rules_ok = violations = empty = 0
for q, want_avoid, want_veg in CASES:
    text, avoid, veg = rewrite(q)
    read_ok = want_avoid <= avoid and veg == want_veg
    rules_ok += read_ok
    top = [c for c, _, _ in search(text, avoid=avoid, vegetarian=veg)]
    bad = [c["title"] for c in top if c["allergens"] & want_avoid or (want_veg and c["vegetarian"] == "no")]
    violations += len(bad)
    empty += not top
    print(f"{'OK ' if read_ok else 'BAD'} rules avoid={sorted(avoid)} veg={veg}  | {q}")
    for c in top:
        print(f"      p.{c['book_page']:<4} {c['title'][:34]:34} allergens={sorted(c['allergens'])} veg={c['vegetarian']}")
    if bad:
        print("      !! VIOLATION:", bad)
print(f"\nrules read right: {len(CASES) - (len(CASES) - rules_ok)}/{len(CASES)} | violations in top 3: {violations}"
      f"  <- must be 0 | empty results: {empty} | ${sum(h.get('cost') or 0 for h in LM.history):.4f}")
