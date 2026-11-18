# Resources: Broke Student Grocery Agent

Every link was checked on 2026-11-17 (it loaded, or its API answered). They're in learning order: read a stage, build
that stage, then move to the next.

## Accounts to create first

| What | Where | Cost | Env var |
|---|---|---|---|
| Kroger developer app | https://developer.kroger.com/ (register an app, scope `product.compact`) | free | `KROGER_CLIENT_ID`, `KROGER_CLIENT_SECRET` |
| BLS API key (optional: without one you get 25 calls/day, with one 500) | https://data.bls.gov/registrationEngine/ | free | `BLS_API_KEY` |
| USDA FoodData Central key (optional) | https://fdc.nal.usda.gov/api-guide | free | `FDC_API_KEY` |
| Anthropic | already have | paid | `ANTHROPIC_API_KEY` |

Put keys in this folder's `.env` (copied from `.env.example`, ignored by git, readable only by you). No key needed: Open Food Facts, Open Prices.

## Stage 1: getting data from an API (OAuth2 + Kroger)

| Resource | Read | Why it matters here |
|---|---|---|
| [OAuth2 client credentials, explained](https://www.oauth.com/oauth2-servers/access-tokens/client-credentials/) | whole page (5 min) | This is how our app logs in as itself (there's no user login). It's the first thing piece 1 does. |
| [RFC 6749 section 4.4](https://datatracker.ietf.org/doc/html/rfc6749#section-4.4) | section 4.4 only | The official spec, so you can say "client-credentials grant" precisely in an interview. |
| [Kroger quick start](https://developer.kroger.com/documentation/public/getting-started/quick-start) | whole page | Registering an app, the token URL, scopes. |
| [Kroger Location API](https://developer.kroger.com/api-products/api/location-api-public) | `filter.zipCode.near`, `locationId` | Turns a ZIP code into a store. |
| [Kroger Product API](https://developer.kroger.com/api-products/api/product-api-public) | `filter.term`, `filter.locationId`, the `price` object (regular vs promo), `size` | Where the real prices come from. Prices only show up when you pass a store. |

## Stage 2: nutrition and "is this a good price?"

| Resource | Read | Why |
|---|---|---|
| [Open Food Facts API](https://openfoodfacts.github.io/openfoodfacts-server/api/) | product by barcode (v2), the `nutriments` and `allergens_tags` fields | Kcal, protein and allergens per UPC. Try a live example: https://world.openfoodfacts.org/api/v2/product/737628064502.json |
| [USDA FoodData Central API](https://fdc.nal.usda.gov/api-guide) | search + food details | A backup for loose items with no barcode (bananas, dry beans). Its data is more reliable than crowdsourced data. |
| BLS average prices: https://www.bls.gov/cpi/factsheets/average-prices.htm (blocks scripts, so open it in a browser) | how the series IDs work (`APU0000...`) | National baseline. Tested: rice, series `APU0000701312`, was **$1.101/lb (Oct 2026)**. |
| [Open Prices API](https://prices.openfoodfacts.org/api/docs) | `GET /api/v1/prices` | Optional crowdsourced prices; **345,108 prices** in the database today. |

## Stage 3: unit prices + caching

| Resource | Read | Why |
|---|---|---|
| [requests-cache](https://requests-cache.readthedocs.io/) | "expiration" section | Caches Kroger answers for a week, so we stay under the rate limit. It's one line of setup. |

Unit-price normalization ("2 lb" vs "32 oz" vs "12 ct") is code we write ourselves; there's nothing to read.

## Stage 4: the optimizer (the main math lesson)

| Resource | Read | Why |
|---|---|---|
| [PuLP docs](https://coin-or.github.io/pulp/) | "Optimisation concepts" page | Linear programming in 10 minutes: variables, objective, constraints. |
| [PuLP blending problem](https://coin-or.github.io/pulp/CaseStudies/a_blending_problem.html) | the whole case study | Nearly the same problem as ours: the cheapest mix of ingredients that hits nutrient minimums. The original version is the "Stigler diet problem" (1945). |
| [USDA food plan costs](https://www.fns.usda.gov/cnpp/usda-food-plans-cost-food-monthly-reports) | Thrifty plan, monthly report | A real-world check on our numbers: what the government says a cheap week of food costs. Compare it to our $60. |
| [Dietary Guidelines](https://www.dietaryguidelines.gov/) | protein and calorie ranges only | Where the protein floor comes from. Basic guidance only, never medical advice. |

## Stage 5: the agent

| Resource | Read | Why |
|---|---|---|
| [Claude tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) | the tool-use loop, `tool_use` / `tool_result` | Option A for the agent: a raw tool loop (you've built one before). |
| [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) | state, nodes, interrupt | Option B for the agent (you've built this too, in agent_graph.py). |

## Stage 6: delivery (stretch)

| Resource | Read | Why |
|---|---|---|
| [discord.py](https://discordpy.readthedocs.io/) | quickstart, slash commands | If we choose the Discord bot over the CLI. |
