"""Extraction eval: run read_page.py on the 10 gold spreads (x reps), grade every card field by code.

Usage: python3 -I recipes_rag/evals/eval_extract.py [haiku|opus] [reps]      # run + grade
       python3 -I recipes_rag/evals/eval_extract.py haiku 2 --score-only    # grade saved runs ($0)
"""
import json
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLD = {int(k): v for k, v in json.load(open(HERE / "gold_extraction.json")).items() if k.isdigit()}
FIELDS = ["kind", "category", "book_page", "unit_cost", "cost_unit", "photo", "n_ingredients", "n_pick_one_groups"]
who = sys.argv[1] if len(sys.argv) > 1 else "haiku"
reps = int(sys.argv[2]) if len(sys.argv) > 2 else 2
run_dir = lambda r: HERE / "runs" / f"{who}_r{r}"


def run_one(job):
    """Run read_page.py on one (spread, rep) into the eval's own folder; return what it cost in $."""
    n, r = job
    out = subprocess.run([sys.executable, "-I", str(HERE.parent / "read_page.py"), str(n), who, str(run_dir(r))],
                         capture_output=True, text=True).stdout
    return float((re.findall(r"\$(\d+\.\d{4})", out) or ["0"])[0])


def norm(t):
    """Lowercase a title and drop punctuation, so "Don't Buy Drinks" matches "Dont buy drinks"."""
    return re.sub(r"[^a-z0-9 ]", "", t.lower().replace("’", "'").replace("'", ""))


def got_value(card, field):
    """Read a field from Haiku's card in the same shape the gold file uses (e.g. count ingredients)."""
    if field == "photo":
        return card["photo_id"]
    if field == "n_ingredients":
        return sum(len(g["items"]) for g in card["ingredient_groups"])
    if field == "n_pick_one_groups":
        return sum(1 for g in card["ingredient_groups"] if g["pick_one_of"])
    return card[field]


def same(field, gold, got):
    """Is Haiku's value right? Photo: any listed id; unit: ignore plural 's'; prices: within half a cent."""
    if field == "photo":
        return got in gold
    if field == "cost_unit":
        return (got or "").lower().rstrip("s") == gold
    if isinstance(gold, float):
        return got is not None and abs(got - gold) < 0.005
    return got == gold


def grade(r):
    """Score one run: match each gold card to Haiku's card by title, then check every field.
    Returns found, total, extra cards, per-field right/graded counts, the misses, and values for stability."""
    found = total = extra = 0
    field_ok, field_n, misses, values = Counter(), Counter(), [], {}
    for n, gold_cards in GOLD.items():
        pred = [c for c in json.load(open(run_dir(r) / f"pdf{n:03d}_{who}.json")) if c["kind"] != "section"]
        free = list(range(len(pred)))
        for g in gold_cards:
            total += 1
            scores = [(SequenceMatcher(None, norm(g["title"]), norm(pred[i]["title"])).ratio(), i) for i in free]
            best, i = max(scores, default=(0, None))
            if best < 0.75:
                misses.append(f"PDF {n}: MISSING '{g['title']}'")
                values[(n, g["title"])] = "missing"
                continue
            found += 1
            free.remove(i)
            values[(n, g["title"])] = tuple(got_value(pred[i], f) for f in FIELDS if f in g)
            for f in FIELDS:
                if f in g and g[f] is not None or f == "photo":
                    field_n[f] += 1
                    if same(f, g[f], got_value(pred[i], f)):
                        field_ok[f] += 1
                    else:
                        misses.append(f"PDF {n}: '{g['title']}' {f}: gold {g[f]} got {got_value(pred[i], f)}")
        extra += len(free)
        misses += [f"PDF {n}: EXTRA card '{pred[i]['title']}'" for i in free]
    return found, total, extra, field_ok, field_n, misses, values


if "--score-only" not in sys.argv:
    jobs = [(n, r) for r in range(1, reps + 1) for n in GOLD]
    with ThreadPoolExecutor(max_workers=6) as pool:
        cost = sum(pool.map(run_one, jobs))
    print(f"ran {len(jobs)} extractions ({len(GOLD)} spreads x {reps}), ${cost:.4f}")

results = [grade(r) for r in range(1, reps + 1)]
for r, (found, total, extra, ok, n, misses, _) in enumerate(results, 1):
    print(f"\nrun {r}: recall {found}/{total} = {found / total:.0%} | precision {found}/{found + extra}"
          f" = {found / (found + extra):.0%}")
    print("  fields: " + ", ".join(f"{f} {ok[f]}/{n[f]}" for f in FIELDS if n[f]))
    for m in misses:
        print("   -", m)
keys = results[0][6].keys()
stable = sum(1 for k in keys if len({res[6][k] for res in results}) == 1)
print(f"\nstability: {stable}/{len(keys)} gold cards identical across {reps} runs")
