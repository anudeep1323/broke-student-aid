# Broke Student Aid: build plan

Rule: Claude does the language (understand the request, explain), code does facts and math.

| # | Step | Status | You learn |
|---|---|---|---|
| 0 | Accounts and keys (Kroger, BLS, USDA FDC, Anthropic) | ✅ done | OAuth2 client credentials, keys in .env, never committed |
| 1 | Kroger: ZIP -> store -> prices | ✅ done (rice $0.95/lb, 14% below BLS avg) | Calling a real API with a token; "on sale" is not "cheap" |
| 2 | Get the cookbook: Good and Cheap PDF -> text -> one chunk per recipe | ✅ done (v2: Claude reads pages -> 95 recipe cards + 31 ideas, 92 with photos, $0.09) | PDF extraction, chunking by structure (recipe = chunk), page numbers kept for citations |
| 3 | Recipe search: "vegetarian, no peanuts, 20 min" -> top recipes cited by page | ⏳ next | Hybrid RAG (BM25 + vectors), metadata filters, retrieval evals |
| 4 | Price a recipe: ingredients -> Kroger price -> $/serving | todo | Unit-price parsing (oz/onz/lb/lbr), ingredient -> product matching |
| 5 | Nutrition and allergens per product | todo | Open Food Facts by UPC, USDA fallback, joining data sources |
| 6 | Ready-made food (frozen/prepared), priced the same way | todo | Reusing one pricing pipeline for a second product type |
| 7 | Plan the week within budget + protein target | todo (choice: PuLP vs Claude + code check) | Constraint optimization vs LLM-proposes-code-verifies |
| 8 | The agent: Claude + tools loop, explains choices and swaps | todo (choice: raw loop vs LangGraph) | Tool calling, keeping math out of the LLM |
| 9 | Weekly price cache | todo | TTL caching, API rate limits |
| 10 | Evals on 20 student profiles | todo | Pass/fail checks: under budget, allergens respected, protein met |
| 11 | Interface | todo (choice: CLI vs Discord) | Shipping it so someone can use it |

## Where each step lives (one folder per skill)

| Folder | Steps | Holds |
|---|---|---|
| `setup/` | 0 | check_keys.py |
| `kroger/` | 1, 4, 6, 9 | store lookup, prices, unit parsing, price cache |
| `recipes_rag/` | 2, 3 | PDF -> pages -> recipes, recipe search; own `data/` (gitignored) |
| `nutrition/` | 5 | Open Food Facts / USDA (later) |
| `planner/` | 7 | week plan within budget (later) |
| `agent/` | 8, 10, 11 | Claude tool loop, evals, interface (later) |
