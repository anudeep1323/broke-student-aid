"""Check each API key works. Prints OK/MISSING/FAILED per service, never the key itself."""
import os, requests
from pathlib import Path
from dotenv import load_dotenv

# Keys live in this project's own .env (ignored by git), never the lab's.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

def env(name):
    """Read one key from the environment (empty string if missing)."""
    return os.environ.get(name, "").strip()

def check(name, needed, test):
    """Print OK / MISSING / FAIL for one service: are its keys set, and does a real test call work?"""
    if not all(env(n) for n in needed):
        return print(f"{name:14} MISSING  set {', '.join(needed)}")
    try:
        print(f"{name:14} OK       {test()}")
    except Exception as e:  # show the error type and HTTP status only, never the request (it holds the key)
        print(f"{name:14} FAILED   {type(e).__name__}: {getattr(getattr(e, 'response', None), 'status_code', '')}")

def kroger():
    """Test call: get a Kroger access token with the client id + secret."""
    r = requests.post("https://api.kroger.com/v1/connect/oauth2/token", timeout=10,
                      auth=(env("KROGER_CLIENT_ID"), env("KROGER_CLIENT_SECRET")),
                      data={"grant_type": "client_credentials", "scope": "product.compact"})
    r.raise_for_status()
    return f"token valid for {r.json()['expires_in']}s"

def bls():
    """Test call: fetch one BLS average-price series."""
    r = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", timeout=15,
                      json={"seriesid": ["APU0000701312"], "registrationkey": env("BLS_API_KEY")})
    r.raise_for_status()
    return f"status {r.json()['status']}"

def fdc():
    """Test call: search USDA FoodData Central for 'rice'."""
    r = requests.get("https://api.nal.usda.gov/fdc/v1/foods/search", timeout=15,
                     params={"query": "rice", "pageSize": 1, "api_key": env("FDC_API_KEY")})
    r.raise_for_status()
    return f"{r.json()['totalHits']} foods match 'rice'"

def anthropic():
    """Test call: list Claude models with the Anthropic key."""
    r = requests.get("https://api.anthropic.com/v1/models", timeout=10,
                     headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"})
    r.raise_for_status()
    return f"{len(r.json()['data'])} models visible"

check("Kroger", ["KROGER_CLIENT_ID", "KROGER_CLIENT_SECRET"], kroger)
check("BLS", ["BLS_API_KEY"], bls)
check("USDA FDC", ["FDC_API_KEY"], fdc)
check("Anthropic", ["ANTHROPIC_API_KEY"], anthropic)
