"""Stage 2, piece 2: add printed book page numbers to pages.json.

Each PDF page is a 2-page spread: PDF page n = book pages 2n-4 (left) and 2n-3 (right).
We use the rule, then check it against the page numbers printed in the text itself.
"""
import json
from pathlib import Path
import re

DATA = Path(__file__).resolve().parent / "data"  # this skill's own data folder

pages = json.load(open(DATA / "pages.json"))
agree, disagree, no_number = 0, [], 0

for p in pages:
    left = 2 * p["page"] - 4
    p["printed"] = [n for n in (left, left + 1) if n >= 1]  # PDF 1-2 = cover, unnumbered
    seen = {int(l) for l in p["text"].split("\n") if re.fullmatch(r"\d{1,3}", l.strip())}
    if not seen:
        no_number += 1
    elif seen & set(p["printed"]):
        agree += 1
    else:
        disagree.append((p["page"], p["printed"], sorted(seen)))

json.dump(pages, open(DATA / "pages.json", "w"), indent=1, ensure_ascii=False)
print(f"rule agrees with printed number: {agree}/{len(pages)} | no number on page: {no_number}")
print(f"disagree: {disagree}")
print(f"example: PDF page 30 -> book pages {pages[29]['printed']}")
