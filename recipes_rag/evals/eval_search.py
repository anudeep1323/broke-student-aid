"""Search eval: ask the 20 gold questions, score the top 3 by code (no LLM, $0).

Usage: python3 -I recipes_rag/evals/eval_search.py             # baseline: raw question
       python3 -I recipes_rag/evals/eval_search.py --rewrite   # Claude rewrites it first (DSPy)
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))        # -I hides the script folder; add recipes_rag/ to import search.py
from search import cards, search            # noqa: E402  (loads cards + model once)

GOLD = json.load(open(HERE / "gold_search.json"))["questions"]
REWRITE = "--rewrite" in sys.argv
if REWRITE:
    from rewrite import LM, rewrite  # noqa: E402


def norm(t):
    """Lowercase a title and drop punctuation, so "My Dad’s Baked Beans" matches "My Dads Baked Beans"."""
    return re.sub(r"[^a-z0-9 ]", "", t.lower().replace("’", "'").replace("'", ""))


def is_right(card, g):
    """A result is right if its title is in the gold titles OR its category is a gold category."""
    return norm(card["title"]) in {norm(t) for t in g["titles"]} or card["category"] in g["categories"]


card_titles = {norm(c["title"]) for c in cards}
unknown = sorted({t for g in GOLD for t in g["titles"] if norm(t) not in card_titles})
if unknown:                                  # a typo in the answer key would silently score as a miss
    sys.exit(f"gold titles that match no card (fix gold_search.json): {unknown}")

if __name__ == "__main__":                   # importable: optimize_rewrite.py reuses norm / is_right
    hits = right_total = 0
    print(f"{len(GOLD)} questions over {len(cards)} cards\n")
    for g in GOLD:
        query, avoid, veg = rewrite(g["q"]) if REWRITE else (g["q"], set(), False)
        top = [c for c, _, _ in search(query, avoid=avoid, vegetarian=veg)]
        marks = [is_right(c, g) for c in top]
        hits += any(marks)
        right_total += sum(marks)
        print(f"{'HIT ' if any(marks) else 'MISS'} {sum(marks)}/3  {g['q'][:38]:38} -> "
              + " | ".join(f"{'✓' if m else '✗'} {c['title'][:22]}" for c, m in zip(top, marks)))
        if REWRITE:
            print(f"           rewritten: {query[:110]}")
    print(f"\nhit@3 {hits}/{len(GOLD)} = {hits / len(GOLD):.0%} | precision@3 {right_total}/{3 * len(GOLD)}"
          f" = {right_total / (3 * len(GOLD)):.0%}")
    if REWRITE:
        cost = sum(h.get("cost") or 0 for h in LM.history)
        print(f"rewrite calls: {len(LM.history)}, ${cost:.4f}")
