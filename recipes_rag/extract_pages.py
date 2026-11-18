"""Stage 2, piece 1: cookbook PDF -> pages.json, one {page, text} per page."""
import json
from pathlib import Path
import sys
import time

import pymupdf  # PyMuPDF (new name; "fitz" is deprecated)

DATA = Path(__file__).resolve().parent / "data"  # this skill's own data folder

src = sys.argv[1] if len(sys.argv) > 1 else str(DATA / "raw" / "good-and-cheap.pdf")
out = DATA / "pages.json"

t0 = time.time()
doc = pymupdf.open(src)
pages = [{"page": i + 1, "text": p.get_text("text")} for i, p in enumerate(doc)]

with open(out, "w") as f:
    json.dump(pages, f, indent=1, ensure_ascii=False)

empty = [p["page"] for p in pages if len(p["text"].strip()) < 20]
chars = sum(len(p["text"]) for p in pages)
print(f"{len(pages)} pages, {chars:,} chars, {time.time() - t0:.2f}s -> {out}")
print(f"near-empty pages (photos?): {len(empty)} {empty[:15]}")
