# Broke Student Aid: charter and plan

Status updated: 2026-11-18. Update this file at every pivot or finished piece; ARCHITECTURE.md is the build log, this is the map.

## Mission (read this first)

**The problem.** A college student with $25 left for the week walks into a grocery store and doesn't know
what to buy, what it will cost, or what to cook with it. So they overspend on snacks, eat the same rice all week,
or skip meals. Cheap, healthy recipes exist (the free cookbook *Good and Cheap* was written for exactly this budget),
but nothing connects those recipes to what's on the shelf at *their* store today, at *today's* prices.

**What Broke Student Aid does.** It is a shopping and cooking helper. The student tells it three things:
where they are (ZIP code), how much they can spend, and what they want in their own words.
It answers with a short shopping list from their nearest Kroger, with real prices that add up to less than their budget,
and 2-3 recipes from the cookbook they can cook with exactly those groceries, with photos and page numbers.

**Example.** Maya types ZIP 45202, $25, and "I'm broke till Friday, no peanuts, tired of rice, want something warm".
She gets: Dal (lentil soup, p.35) and Corn Soup (p.36); lentils $1.49, onions $2.99, frozen corn $3.19 ...;
total $22.60, $2.40 left; nothing with peanuts.

**Promises it must keep** (or a student gets hurt or embarrassed at the till):
- Every price is real, from the store's own data, and the total adds up. Never a made-up number.
- It never goes over the budget.
- It never suggests food the student said they're allergic to.

**Why I'm building it.** It's my showcase for AI-engineer interviews: a real problem, real store data,
and the core skills (search over documents, an AI agent that uses tools, safety checks, measured quality and cost).

**How it works, in one line:** the AI understands the request and writes the plan; plain code finds prices,
adds them up and checks allergens, because those must never be guessed.

**MVP is done when:**
1. A student types ZIP + budget in fields and one sentence in a chat box (Streamlit), and gets the plan with recipe photos.
2. The agent eval passes all 5 checks on 10/10 cases (within budget, total matches items, no made-up prices, diet respected, real pages).
3. Cost is at or under **$0.05 per answer** (now $0.057) and time under **30 s** (now ~35 s).
4. Code, evals and diagrams are pushed to github.com/anudeep1323/broke-student-aid with a README.

**Out of scope for the MVP** (next version): nutrition + protein target, ready-made / frozen meals, a weekly price cache, deployment, the 20-profile eval.

**Targets I'll quote in interviews:** extraction 34/34 cards, allergen recall 100%, search hit@3 75% -> 95% with the rewrite, agent $0.15 -> target $0.05 per answer.

## Milestones (MVP)

| # | Milestone | Status | Proof / numbers | You learn |
|---|---|---|---|---|
| M0 | Keys + Kroger prices (ZIP -> store -> products) | ✅ | rice $0.76/lb, 4.6 s for 3 searches | OAuth2 client credentials; "on sale" is not "cheap" |
| M1 | Cookbook -> recipe cards (Claude reads pages) | ✅ | 95 recipes, 92 photos, $0.097; extraction eval 34/34 | Structured extraction + an answer key |
| M2 | Recipe search + question rewrite (DSPy) | ✅ | hit@3 75% -> 95%; few-shot rejected (worse on held-out) | Hybrid RAG, held-out evals |
| M3 | Allergen + vegetarian filters (code) | ✅ | recall 55/55, rules 8/8, 0 violations | Safety by code, not by LLM |
| M4 | Grocery-first flow: browse, basket, basket -> recipes | ✅ | basket $7.98 of $30; rice + eggs -> 5 recipes | Unit-price parsing, ingredient matching |
| M5 | Agent: Haiku gathers, Opus decides + writes (LangGraph) | 🔶 works | $0.0625, 38 s, total matches items | Matching jobs to models; handoffs carry decisions |
| M6 | Agent eval (10 cases, 5 code checks) merged into one `run_evals.py` | ✅ | 10/10 cases pass all 5 checks; $0.057 and ~35 s per answer | Component vs end-to-end evals |
| M7 | Cost/quality tuning with the agent eval (2 vs 5 options, Opus effort) | ⬜ | target <= $0.05, 10/10 | Measured trade-offs |
| M8 | Streamlit: agent chat wired in beside ZIP + budget, photos | ⬜ (screen 1 exists, UI will change) | - | Shipping it |
| M9 | README + commit + push | ⬜ (first commit pushed; much since uncommitted) | - | Presenting the work |

**Next up:** M7 (cut $0.057 -> $0.05 and ~35 s -> 30 s without dropping below 10/10), then M8.

## After the MVP (backlog)

| Item | Why later |
|---|---|
| Nutrition per product (Open Food Facts) + protein target | Not needed to buy within budget; adds a data source |
| Ready-made / frozen meals | Same pricing pipeline, second product type |
| Weekly price cache | Streamlit caches 1 h today; only matters with real users |
| 20-profile agent eval | Grow from 10 once real student sentences exist |
| Deploy | After the UI settles |

## Where things live (one folder per skill)

| Folder | Holds |
|---|---|
| `setup/` | check_keys.py |
| `kroger/` | browse.py (store, products, unit prices), kroger_piece1.py |
| `recipes_rag/` | PDF -> cards (read_page.py, run_all.py), search.py, rewrite.py (DSPy), diet.py, evals/; own `data/` (gitignored) |
| `grocery/` | ingredients.py (plain names), match.py (basket -> recipes) |
| `agent/` | tools.py (5 tools), graph.py (LangGraph), evals/eval_agent.py |
| `app.py` | Streamlit screen 1 |
