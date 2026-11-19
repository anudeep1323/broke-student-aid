"""One command for every eval. Component evals (each tests one part alone) are free; the agent eval costs money.

python3 -I run_evals.py           -> extraction, search, diet, rules        (~$0, run after every change)
python3 -I run_evals.py --agent   -> the same + 10 end-to-end agent cases   (~$0.60, before trusting a cost change)
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
SECTIONS = [  # (name, what it tests, command, regex for the score line(s) to show)
    ("extraction", "Haiku reading cookbook pages into cards", ["recipes_rag/evals/eval_extract.py", "haiku", "2", "--score-only"],
     r"^run \d: recall|^stability"),
    ("search (raw)", "hybrid search on 20 questions", ["recipes_rag/evals/eval_search.py"], r"^hit@3"),
    ("search (+rewrite)", "DSPy question rewrite + search", ["recipes_rag/evals/eval_search.py", "--rewrite"], r"^hit@3"),
    ("diet", "allergen + vegetarian code on 22 trap cards", ["recipes_rag/evals/eval_diet.py"], r"^allergen RECALL|^vegetarian"),
    ("rules", "reading 'no peanuts' + filtering results", ["recipes_rag/evals/eval_rules.py"], r"^rules read right"),
]
if "--agent" in sys.argv:
    SECTIONS.append(("agent (end to end)", "10 student sentences, 5 code checks each", ["agent/evals/eval_agent.py", "baseline"],
                     r"^\[baseline\]|^FAIL|^\s+x "))


def run(name, what, args, pattern):
    """Run one eval script and print only its score lines (full output on failure)."""
    t0 = time.time()
    p = subprocess.run([PY, "-I", *args], cwd=ROOT, capture_output=True, text=True)
    lines = [l for l in p.stdout.splitlines() if re.search(pattern, l)]
    print(f"\n== {name}: {what}  ({time.time() - t0:.0f}s)")
    if p.returncode != 0 or not lines:
        print("   !! eval did not finish:\n" + "\n".join("   " + l for l in (p.stdout + p.stderr).strip().splitlines()[-8:]))
    for l in lines:
        print("   " + l.strip())


for section in SECTIONS:
    run(*section)
