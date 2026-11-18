"""Stage 2 v2: run read_page.py on every spread, 6 at a time; skip spreads already done.

Usage: python3 -I recipes_rag/run_all.py [haiku|opus]
"""
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
who = sys.argv[1] if len(sys.argv) > 1 else "haiku"
N_PAGES = 90


def run(n):
    """Read one spread with read_page.py (skip if its card file exists); return its summary lines."""
    if (HERE / "data" / "cards" / f"pdf{n:03d}_{who}.json").exists():
        return n, "skipped (already done)"           # re-runs cost $0 for finished spreads
    r = subprocess.run([sys.executable, "-I", str(HERE / "read_page.py"), str(n), who],
                       capture_output=True, text=True)
    lines = (r.stdout + r.stderr).strip().splitlines()
    return n, "\n".join(lines[:1] + [l for l in lines if l.startswith(("checks", "stopped", "Traceback"))
                                     or "Error" in l])


t0 = time.time()
with ThreadPoolExecutor(max_workers=6) as pool:
    results = sorted(pool.map(run, range(1, N_PAGES + 1)))
cost = sum(float(m) for _, out in results for m in re.findall(r"\$(\d+\.\d{4})", out))
bad = [(n, out) for n, out in results if "all passed" not in out and "skipped" not in out]
print(f"{N_PAGES} spreads in {time.time() - t0:.0f}s, cost this run ${cost:.4f}, {len(bad)} need a look:")
for n, out in bad:
    print(f"--- PDF {n}\n{out}")
