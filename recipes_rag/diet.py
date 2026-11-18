"""Stage 3 piece 4: work out allergens + vegetarian from a card's ingredients, by code ($0, same answer every time).

No LLM here on purpose: a missed allergen is a safety bug, so the rule must be checkable line by line.
"""
import re

# "False friends": words that LOOK like an allergen but aren't. Replaced before matching.
FALSE_FRIENDS = {
    "peanut butter": "peanut", "butternut": "squash", "eggplant": "aubergine", "nutmeg": "spice",
    "coconut milk": "coconut", "almond milk": "almond", "rice milk": "rice", "cream of tartar": "tartar",
    "butter knife": "knife",   # found by the eval: Tilapia's steps test doneness "with a butter knife"
}
ALLERGENS = {   # allergen -> whole words that mean it (regex, matched on word boundaries)
    "peanut": r"peanuts?",
    "tree_nut": r"nuts?|almonds?|walnuts?|pecans?|cashews?|pistachios?|hazelnuts?|pine nuts?",
    "milk": r"milk|butter|buttermilk|cheese|cheddar|parmesan|romano|mozzarella|feta|ricotta|cream|yogh?urt|ghee|raita|tzatziki",
    "egg": r"eggs?|yolks?|mayo|mayonnaise",
    "wheat": r"flour|bread|toast|croutons?|breadcrumbs|pasta|spaghetti|rigatoni|fettuccine|noodles?|wraps?|tortillas?|roti|"
             r"pita|naan|dough|crackers?|couscous|bulgur|panko|soy sauce|calzones?|scones?",
    "soy": r"soy|tofu|edamame|miso|tempeh",
    "fish": r"fish|tilapia|salmon|tuna|cod|anchov(?:y|ies)|sardines?",
    "shellfish": r"shrimps?|prawns?|crabs?|lobsters?|clams?|mussels?|scallops?",
    "sesame": r"sesame|tahini",
}
MEAT = r"chicken|beef|pork|bacon|sausages?|chorizo|ham|turkey|lamb|schmaltz|steak|" + ALLERGENS["fish"] + "|" + ALLERGENS["shellfish"]
OPTIONAL_GROUP = re.compile(r"addition|optional|variation|extra|topping idea", re.I)


def clean(text):
    """Lowercase and swap false friends ('butternut' -> 'squash') so they can't match."""
    text = text.lower()
    for phrase, safe in FALSE_FRIENDS.items():
        text = text.replace(phrase, safe)
    return text


def has(pattern, text):
    """True if any of the pattern's words appear as whole words in the cleaned text."""
    return re.search(rf"\b(?:{pattern})\b", clean(text)) is not None


def card_text(card):
    """Everything a student would read: title + every ingredient + steps."""
    items = " ; ".join(i for g in card["ingredient_groups"] for i in g["items"])
    return f"{card['title']} ; {items} ; {card['steps']}"


def allergens(card, by_page, seen=()):
    """Allergens in this card, plus any recipe it points to with '(p. 164)' (raita -> yogurt). Optional items count."""
    text = card_text(card)
    found = {a for a, pattern in ALLERGENS.items() if has(pattern, text)}
    for page in re.findall(r"\(p\.\s*(\d+)", text):
        for ref in by_page.get(int(page), []):
            if id(ref) not in seen and ref is not card:
                found |= allergens(ref, by_page, seen + (id(card),))
    return found


def vegetarian(card):
    """'no' if a required ingredient is meat/fish; 'option' if meat only in optional/additions/one pick-one choice; else 'yes'."""
    groups = card["ingredient_groups"]
    if not any(g["items"] for g in groups):                  # idea cards: only the text to go on
        return "no" if has(MEAT, card["title"] + " " + card["steps"]) else "yes"
    result = "yes"
    for g in groups:
        meaty = [i for i in g["items"] if has(MEAT, i)]
        if not meaty:
            continue
        optional = OPTIONAL_GROUP.search(g["name"] or "") or all("optional" in i.lower() for i in meaty)
        if g["pick_one_of"]:
            alternatives = [h for h in groups if h["pick_one_of"] == g["pick_one_of"] and h is not g]
            optional = optional or any(not any(has(MEAT, i) for i in h["items"]) for h in alternatives)
        if not optional:
            return "no"
        result = "option"
    return result
