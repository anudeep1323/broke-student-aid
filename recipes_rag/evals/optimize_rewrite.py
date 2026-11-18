"""DSPy BootstrapFewShot: improve the question rewrite with worked examples, scored by our search eval.

Train on 10 questions, test on the other 10 (never seen during training).
Saves the few-shot prompt to recipes_rag/rewrite_fewshot.json (NOT used: it scored worse, see ARCHITECTURE.md).
Usage: python3 -I recipes_rag/evals/optimize_rewrite.py
"""
import random
import sys
from pathlib import Path

import dspy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from eval_search import GOLD, is_right   # noqa: E402  (answer key + "is this card right?")
from rewrite import LM, Rewrite          # noqa: E402  (configures Haiku via DSPy)
from search import search                # noqa: E402

SAVE = HERE.parent / "rewrite_fewshot.json"
qs = GOLD[:]
random.Random(7).shuffle(qs)             # fixed seed: same split every run
examples = [dspy.Example(question=g["q"], gold=g).with_inputs("question") for g in qs]
train, test = examples[:10], examples[10:]


def precision3(example, pred, trace=None):
    """Score one rewrite: run search on it, count right cards in the top 3 (0, 1/3, 2/3 or 1).
    While bootstrapping (trace set), a rewrite only becomes an example if it got at least 2 of 3 right."""
    top = [c for c, _, _ in search(pred.search_text)]
    p = sum(is_right(c, example.gold) for c in top) / 3
    return p if trace is None else p >= 2 / 3


def score(program, exs):
    """hit@3 and precision@3 of a rewrite program over some examples."""
    ps = [precision3(e, program(question=e.question)) for e in exs]
    return sum(p > 0 for p in ps), sum(round(p * 3) for p in ps), len(exs)


print("train:", [e.question for e in train])
print("test: ", [e.question for e in test], "\n")

zero = dspy.Predict(Rewrite)
h, r, n = score(zero, test)
print(f"zero-shot on TEST: hit@3 {h}/{n}, precision@3 {r}/{3 * n}")

calls_before = len(LM.history)
opt = dspy.BootstrapFewShot(metric=precision3, max_bootstrapped_demos=4, max_labeled_demos=0)
fewshot = opt.compile(dspy.Predict(Rewrite), trainset=train)
h2, r2, n = score(fewshot, test)
print(f"few-shot  on TEST: hit@3 {h2}/{n}, precision@3 {r2}/{3 * n}")

print("\nexamples DSPy put in the prompt (rewrites that scored >= 2/3 on train):")
for d in fewshot.demos:
    print(f"  '{d.question}' -> '{d.search_text}'")
fewshot.save(str(SAVE))
cost = sum(x.get("cost") or 0 for x in LM.history)
print(f"\nsaved {SAVE.name} | Claude calls: {len(LM.history)} ({len(LM.history) - calls_before} for optimising), ${cost:.4f}")
