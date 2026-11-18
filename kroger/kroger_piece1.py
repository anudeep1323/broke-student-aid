"""Piece 1: Kroger token -> nearest store -> 5 rice prices. Keys come from env vars only."""
import os, sys, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # this project's keys only

API = "https://api.kroger.com/v1"
ZIP = sys.argv[1] if len(sys.argv) > 1 else "45202"

# 1. Token: OAuth2 client-credentials (app-level, no user login). Never printed.
tok = requests.post(f"{API}/connect/oauth2/token",
                    auth=(os.environ["KROGER_CLIENT_ID"], os.environ["KROGER_CLIENT_SECRET"]),
                    data={"grant_type": "client_credentials", "scope": "product.compact"}, timeout=10)
tok.raise_for_status()
H = {"Authorization": f"Bearer {tok.json()['access_token']}"}

# 2. Nearest store to the ZIP.
store = requests.get(f"{API}/locations", headers=H, timeout=10,
                     params={"filter.zipCode.near": ZIP, "filter.limit": 1}).json()["data"][0]
print(f"Store: {store['name']} ({store['locationId']}), {store['address']['addressLine1']}")

# 3. Search "rice" at that store; price lives in items[0].price (missing if not stocked there).
prods = requests.get(f"{API}/products", headers=H, timeout=10,
                     params={"filter.term": "rice", "filter.locationId": store["locationId"], "filter.limit": 5}).json()["data"]
for p in prods:
    it = p["items"][0]
    price = it.get("price", {})
    print(f"{p['description'][:45]:45} {it.get('size',''):>8}  reg ${price.get('regular','-')}  promo ${price.get('promo','-')}")
