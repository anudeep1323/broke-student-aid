"""Stage 2 v2 test: Claude reads ONE cookbook spread -> recipe cards with photos, checked by code.

Usage: python3 -I recipes_rag/read_page.py <pdf_page> <haiku|opus> [out_dir]
"""
import base64
import json
import sys
import time
from pathlib import Path
from typing import Literal, Optional

import anthropic
import pymupdf
from dotenv import load_dotenv
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
load_dotenv(HERE.parent / ".env")
MODELS = {"haiku": ("claude-haiku-5-5", 0.10, 0.50), "opus": ("claude-opus-5-5", 4.00, 20.00)}  # $/1M in, out


class Group(BaseModel):
    """One ingredient sub-list, e.g. "Dough" or "Veggie filling"; same pick_one_of = choose one."""
    name: Optional[str]
    items: list[str]
    pick_one_of: Optional[str]  # groups sharing this label are alternatives, e.g. "filling"


class Card(BaseModel):
    """One recipe / idea / tip card: the exact format Claude must fill in for each item on a page."""
    title: str
    kind: Literal["recipe", "idea", "section"]
    category: Literal["breakfast", "soup", "salad", "snack_side", "handheld", "dinner", "big_batch",
                      "staple", "drink", "dessert", "flavor", "tip", "about"]
    book_page: int
    makes: Optional[str]          # "for four", "makes sixty"
    total_cost: Optional[float]
    unit_cost: Optional[float]    # the printed "$Y / <unit>" number
    cost_unit: Optional[str]      # "serving", "dumpling", ...
    ingredient_groups: list[Group]
    steps: str
    photo_id: Optional[str]

    def n_ingredients(self):
        """Count ingredients across all groups (used by the code checks)."""
        return sum(len(g.items) for g in self.ingredient_groups)


class Spread(BaseModel):
    """Claude's whole answer for one spread: a list of cards."""
    cards: list[Card]


def photos_on(page, left_book_page):
    """Save every photo on the spread; describe where it sits so Claude can match it."""
    W, H = page.rect.width, page.rect.height
    out = []
    for xref, *_ in page.get_images(full=True):
        for r in page.get_image_rects(xref):
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2  # use the CENTER, not the left edge
            book = left_book_page + (cx >= W / 2)
            pid = f"p{book}_{len(out) + 1}"
            pix = pymupdf.Pixmap(page.parent, xref)
            if pix.n - pix.alpha > 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            (DATA / "images").mkdir(exist_ok=True)
            pix.save(DATA / "images" / f"{pid}.png")
            where = f"book page {book}, {'top' if cy < H / 2 else 'bottom'} {'left' if cx < W / 2 else 'right'}"
            out.append({"id": pid, "where": where})
    return out


pdf_no, who = int(sys.argv[1]), sys.argv[2]
out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else DATA / "cards"  # evals write elsewhere
model, price_in, price_out = MODELS[who]
page = pymupdf.open(DATA / "raw" / "good-and-cheap.pdf")[pdf_no - 1]
left = 2 * pdf_no - 4                                   # rule from page_numbers.py
photos = photos_on(page, left)
png = page.get_pixmap(matrix=pymupdf.Matrix(1568 / page.rect.width, 1568 / page.rect.width)).tobytes("png")

prompt = f"""This image is one spread of a budget cookbook: book pages {left} (left) and {left + 1} (right).
Make one card per recipe, idea box, or section page you see. Several recipes can share a page.
A page that is only a photo (even with labels on it) belongs to the card it illustrates: no extra card.
A list of named ideas or tips (e.g. "Chana Masala Wrap (p. 93)") = one card per named item, not one card for the list.
category: the book section the card falls under (the running header, e.g. "BREAKFAST", "BATCHES" = big_batch,
"BITES" = snack_side). Use "tip" for shopping/kitchen advice that is not a dish, "about" for intro/thanks/index.
Copy ingredients and steps faithfully; use the extracted text below for exact wording.
Costs: read the printed "$X total" / "$Y / <unit>" labels; keep the unit word exactly
(serving, dumpling, ...). Null if none. "makes": the yield line as printed ("for four").
Ingredients: keep the book's sub-headings as groups (Dough, Veggie filling...). When the
book offers alternatives ("choose one filling or the other"), give those groups the same
pick_one_of label; otherwise null.
Photos on this spread (match each recipe to its photo by position; null if none):
{json.dumps(photos, indent=1)}

Extracted text:
{page.get_text()}"""

t0 = time.time()
resp = anthropic.Anthropic().messages.parse(
    model=model, max_tokens=16000, output_format=Spread,
    messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.standard_b64encode(png).decode()}},
        {"type": "text", "text": prompt}]}])
secs = time.time() - t0
if resp.stop_reason != "end_turn":
    sys.exit(f"stopped early: {resp.stop_reason}")
cards = resp.parsed_output.cards

# Code checks every card (Claude reads, code verifies)
ids = {p["id"] for p in photos}
problems = []
for c in cards:
    if c.book_page not in (left, left + 1):
        problems.append(f"{c.title}: page {c.book_page} not on this spread")
    if c.kind == "recipe" and c.n_ingredients() < 2:
        problems.append(f"{c.title}: recipe with < 2 ingredients")
    if c.photo_id and c.photo_id not in ids:
        problems.append(f"{c.title}: unknown photo {c.photo_id}")
titles = [c.title.lower().rstrip("!") for c in cards]
for a in titles:
    if any(a != b and a in b for b in titles):
        problems.append(f"duplicate card? '{a}'")
used = [c.photo_id for c in cards if c.photo_id]
if len(used) != len(set(used)):
    problems.append("same photo used twice")

out_dir.mkdir(parents=True, exist_ok=True)
json.dump([c.model_dump() for c in cards], open(out_dir / f"pdf{pdf_no:03d}_{who}.json", "w"), indent=1)
u = resp.usage
cost = u.input_tokens / 1e6 * price_in + u.output_tokens / 1e6 * price_out
print(f"{model}: {len(cards)} cards, {u.input_tokens:,} in / {u.output_tokens:,} out tokens, ${cost:.4f}, {secs:.1f}s")
for c in cards:
    print(f"  p.{c.book_page} [{c.kind}/{c.category}] {c.title} | makes {c.makes} | ${c.total_cost} total,"
          f" ${c.unit_cost}/{c.cost_unit} | {c.n_ingredients()} ingredients | photo {c.photo_id}")
    for g in c.ingredient_groups:
        print(f"      {g.name or '-'} ({len(g.items)}){'  pick one of: ' + g.pick_one_of if g.pick_one_of else ''}")
print("checks:", "all passed" if not problems else problems)
