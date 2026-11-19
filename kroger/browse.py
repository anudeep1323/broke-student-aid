"""Kroger browse: the first thing a student sees. Real products at their nearest Kroger, cheapest per unit first.

Usage: python3 -I kroger/browse.py 45202 rice eggs "black beans"
Keys come from .env only and are never printed.
"""
import os
import re
from collections import Counter
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
API = "https://api.kroger.com/v1"
# size unit -> (family, how many base units it is): weight in lb, volume in fl oz, count in each
UNITS = {"oz": ("lb", 1 / 16), "onz": ("lb", 1 / 16), "lb": ("lb", 1), "lbr": ("lb", 1), "lbs": ("lb", 1), "g": ("lb", 1 / 453.6),
         "kg": ("lb", 2.2046), "fl oz": ("fl oz", 1), "gal": ("fl oz", 128), "qt": ("fl oz", 32), "pt": ("fl oz", 16),
         "l": ("fl oz", 33.81), "ml": ("fl oz", 0.03381), "ct": ("each", 1), "each": ("each", 1), "dozen": ("each", 12)}


def token():
    """Get a Kroger app token (client credentials, no user login). Valid 30 min."""
    r = requests.post(f"{API}/connect/oauth2/token", timeout=10,
                      auth=(os.environ["KROGER_CLIENT_ID"], os.environ["KROGER_CLIENT_SECRET"]),
                      data={"grant_type": "client_credentials", "scope": "product.compact"})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def nearest_store(headers, zip_code):
    """The Kroger store closest to the ZIP: (locationId, display name)."""
    s = requests.get(f"{API}/locations", headers=headers, timeout=10,
                     params={"filter.zipCode.near": zip_code, "filter.limit": 1}).json()["data"][0]
    return s["locationId"], f"{s['name']}, {s['address']['addressLine1']}"


def parse_one(part):
    """'32 oz' -> (2.0, 'lb'); '12 ct' -> (12, 'each'); '1/2 gal' -> (64, 'fl oz'); unknown -> None."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)(?:\s*/\s*(\d+))?\s*(fl oz|[a-z]+)", part.lower())
    if not m or m.group(3) not in UNITS:
        return None
    family, factor = UNITS[m.group(3)]
    return float(m.group(1)) / (float(m.group(2)) if m.group(2) else 1) * factor, family


def parse_size(size):
    """All the ways to read a size: {family: quantity}.
    '4 ct / 15.25 oz' (4 cans) -> {'each': 4, 'lb': 3.81}; '12 ct / 24 oz' (eggs) -> {'each': 12, 'lb': 18.0}.
    browse() then picks the family most products in that search use."""
    parts = [p for p in (parse_one(x) for x in (size or "").split(" / ")) if p]
    out = {fam: qty for qty, fam in parts}
    if len(parts) == 2 and parts[0][1] == "each" and parts[1][1] != "each":   # multipack: N items x size each
        out[parts[1][1]] = parts[0][0] * parts[1][0]
    return out


def get_products(headers, params, tries=4):
    """GET /products with retries: on 429 (too many requests) or a 5xx, wait 1, 2, 4 s (or Retry-After) and try again.
    Any other error raises a clear message instead of a confusing KeyError."""
    for attempt in range(tries):
        r = requests.get(f"{API}/products", headers=headers, timeout=10, params=params)
        if r.status_code == 200 and "data" in r.json():
            return r.json()["data"]
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
            continue
        break
    raise RuntimeError(f"Kroger products failed: HTTP {r.status_code} for {params.get('filter.term')!r}")


def browse(headers, location_id, term, limit=10):
    """Real products for one search word at one store, with best price and unit price, cheapest per unit first."""
    data = get_products(headers, {"filter.term": term, "filter.locationId": location_id, "filter.limit": limit})
    rows = []
    for p in data:
        item = p["items"][0]
        price = item.get("price") or {}
        best = price.get("promo") or price.get("regular")      # promo is 0 when there's no sale
        if not best:
            continue                                            # not sold at this store
        rows.append({"name": p["description"], "size": item.get("size", ""), "regular": price.get("regular"),
                     "promo": price.get("promo") or None, "best": best, "sizes": parse_size(item.get("size")),
                     "product_id": p["productId"]})
    # one unit for the whole list: the family most single-size products use (eggs -> each, beans -> lb)
    common = Counter(f for r in rows if len(r["sizes"]) == 1 for f in r["sizes"]).most_common(1)
    family = common[0][0] if common else "each"
    for r in rows:
        qty = r.pop("sizes").get(family)
        r["unit"], r["unit_price"] = family, (round(r["best"] / qty, 2) if qty else None)
    return sorted(rows, key=lambda r: (r["unit_price"] is None, r["unit_price"] or 0))


if __name__ == "__main__":
    zip_code, terms = sys.argv[1], sys.argv[2:]
    h = token()
    loc, name = nearest_store(h, zip_code)
    print(f"Nearest Kroger to {zip_code}: {name} ({loc})")
    for t in terms:
        rows = browse(h, loc, t)
        print(f"\n'{t}': {len(rows)} products with a price here, cheapest per unit first")
        for r in rows:
            sale = f" SALE ${r['promo']} (reg ${r['regular']})" if r["promo"] else f" ${r['regular']}"
            per = f"${r['unit_price']}/{r['unit']}" if r["unit_price"] else "size?"
            print(f"  {per:>14}  {r['name'][:44]:44} {r['size']:>10}{sale}")
