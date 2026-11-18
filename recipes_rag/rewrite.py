"""Stage 3 piece 3: Claude rewrites a student's question into search words AND pulls out the rules, written with DSPy.

"something warm, I'm allergic to soy" -> search_text "warm soup stew", avoid {soy}, vegetarian False.
A code backstop also reads "allergic to X / no X / X-free" so an LLM miss can never drop a stated allergy.
"""
import re
from pathlib import Path

import dspy
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
# Explicit /v1: this app sets ANTHROPIC_BASE_URL without /v1, and DSPy only appends /messages (-> 404).
LM = dspy.LM("anthropic/claude-haiku-5-5", api_base="https://api.anthropic.com/v1")
dspy.configure(lm=LM)

ALLERGENS = ["peanut", "tree_nut", "milk", "egg", "wheat", "soy", "fish", "shellfish", "sesame"]


class Rewrite(dspy.Signature):
    """Turn a student's food question into search words for a budget cookbook, and pull out their diet rules."""
    question: str = dspy.InputField()
    search_text: str = dspy.OutputField(desc="short keywords naming dishes, ingredients or a cookbook section")
    avoid: list[str] = dspy.OutputField(desc="ONLY allergens the student explicitly says they must NOT eat (an allergy, 'no X', "
                                        "'X-free', 'can't eat X'). Wanting or mentioning a food ('with tofu', 'make pasta') is NEVER "
                                        "a reason to avoid it; do not list allergens that are in the dish. Only from: "
                                        + ", ".join(ALLERGENS) + ". 'nut allergy' = peanut + tree_nut, 'dairy-free' = milk, "
                                        "'gluten-free' = wheat. [] if the student states no restriction.")
    vegetarian: bool = dspy.OutputField(desc="true only if the student asks for no meat/fish (vegetarian, vegan, meat-free)")


rewriter = dspy.Predict(Rewrite)   # DSPy builds the prompt from the Signature

# Code backstop: words a student uses for each allergen, only counted after "no / without / allergic to / avoid / can't eat"
# or before "-free / allergy" (so "what can I make with eggs" does NOT ban eggs).
WORDS = {"peanut": "peanuts?|nuts?", "tree_nut": "tree nuts?|nuts?|almonds?|walnuts?|cashews?", "milk": "dairy|milk|lactose|cheese",
         "egg": "eggs?", "wheat": "gluten|wheat", "soy": "soy|tofu", "fish": "fish", "shellfish": "shellfish|shrimp", "sesame": "sesame"}
NEG_BEFORE = r"(?:no|without|allergic to|avoid|can'?t eat|cannot eat|free of)\s+(?:any\s+)?"
NEG_AFTER = r"(?:-?\s?free|\s+allerg(?:y|ies|ic))"


def backstop(question):
    """Allergens the question clearly rules out, found by code (e.g. 'nut allergy' -> peanut, tree_nut)."""
    q = question.lower()
    return {a for a, w in WORDS.items() if re.search(rf"{NEG_BEFORE}(?:{w})\b|\b(?:{w}){NEG_AFTER}", q)}


def rewrite(question):
    """Ask Claude (through DSPy) for search words + rules; return (search_text, avoid set, vegetarian bool)."""
    p = rewriter(question=question)
    avoid = {a for a in (p.avoid or []) if a in ALLERGENS} | backstop(question)   # union: code can only ADD safety
    veg = bool(p.vegetarian) or re.search(r"\b(vegetarian|vegan|meat-?free|no meat)\b", question.lower()) is not None
    return p.search_text, avoid, veg
