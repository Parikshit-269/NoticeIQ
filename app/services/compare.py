"""Compare extracted facts of two document versions."""
import re

CATEGORIES = ("deadline", "fee", "eligibility", "document")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def _similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def _key(fact: dict) -> str:
    if fact["category"] in ("deadline", "fee") and fact.get("normalized"):
        return fact["normalized"]
    return " ".join(re.findall(r"[a-z0-9%]+", fact["value"].lower()))


def compare_facts(facts_a: list[dict], facts_b: list[dict]) -> dict:
    result = {}
    for cat in CATEGORIES:
        a = {_key(f): f for f in facts_a if f["category"] == cat}
        b = {_key(f): f for f in facts_b if f["category"] == cat}
        removed = [a[k] for k in a if k not in b]
        added = [b[k] for k in b if k not in a]
        changed = []
        if cat in ("deadline", "fee"):
            # Pair a removed and an added value when their context describes the same thing.
            ctx = (lambda f: f["label"]) if cat == "deadline" else (lambda f: f["evidence"])
            for old in list(removed):
                best = max(added, key=lambda n: _similarity(ctx(old), ctx(n)), default=None)
                if best is not None and _similarity(ctx(old), ctx(best)) >= 0.4:
                    changed.append({"before": old, "after": best})
                    removed.remove(old)
                    added.remove(best)
        result[cat] = {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": sum(1 for k in a if k in b),
        }
    return result
