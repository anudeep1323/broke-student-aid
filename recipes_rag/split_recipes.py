"""Stage 2, piece 3: PDF -> recipes.json, one chunk per recipe.

Titles = text blocks in big type (>= 30 pt). Each PDF page is a spread, so we cut it
into a left and a right book page and look for titles in each half.
A recipe's text = from its title down to the next title in the same half.
"""
import json
from pathlib import Path
import re
import sys

import pymupdf

DATA = Path(__file__).resolve().parent / "data"  # this skill's own data folder

src = sys.argv[1] if len(sys.argv) > 1 else str(DATA / "raw" / "good-and-cheap.pdf")
INGREDIENT = re.compile(r"^\t[^\t]*\t\S", re.M)  # "\t4\tlarge sweet potatoes"
recipes = []

for pdf_page in pymupdf.open(src):
    W, H = pdf_page.rect.width, pdf_page.rect.height
    left_book_page = 2 * (pdf_page.number + 1) - 4
    for side, x0 in ((0, 0), (1, W / 2)):  # left half, right half
        half = pymupdf.Rect(x0, 0, x0 + W / 2, H)
        titles = []  # (top y, title text)
        for b in pdf_page.get_text("dict", clip=half)["blocks"]:
            spans = [s for l in b.get("lines", []) for s in l["spans"] if s["text"].strip()]
            if spans and all(30 <= s["size"] < 100 for s in spans):
                titles.append((b["bbox"][1], " ".join(s["text"].strip() for s in spans)))
        titles.sort()
        # untitled right half = continuation of the recipe on the facing left page
        if not titles and side == 1 and recipes and recipes[-1]["pdf_page"] == pdf_page.number + 1:
            more = pdf_page.get_text("text", clip=half)
            recipes[-1]["text"] += more
            recipes[-1]["n_ingredients"] += len(INGREDIENT.findall(more))
            recipes[-1]["continued"] = left_book_page + side
        for i, (y, title) in enumerate(titles):
            y_end = titles[i + 1][0] if i + 1 < len(titles) else H
            body = pdf_page.get_text("text", clip=pymupdf.Rect(x0, y, x0 + W / 2, y_end))
            recipes.append({
                "title": title,
                "book_page": left_book_page + side,
                "pdf_page": pdf_page.number + 1,
                "n_ingredients": len(INGREDIENT.findall(body)),
                "text": body,
            })

json.dump(recipes, open(DATA / "recipes.json", "w"), indent=1, ensure_ascii=False)
real = [r for r in recipes if r["n_ingredients"] >= 2]
print(f"{len(recipes)} titled chunks, {len(real)} with >= 2 ingredient lines (= recipes)")
print("not recipes (sample):", [r["title"] for r in recipes if r["n_ingredients"] < 2][:8])
