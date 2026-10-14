"""Transparent market-mood heuristic from option-chain PCR and India VIX.

This is a rule of thumb, not a prediction. PCR (put OI / call OI) above ~1 means more put
writing — read as support / bullish bias; below ~0.85 the opposite. A high VIX discounts a
bullish read because it signals fear. The returned `reasons` make every call auditable.
"""
from __future__ import annotations


def market_mood(pcr: float | None, vix: float | None) -> dict:
    score = 0
    reasons: list[str] = []

    if pcr is None:
        reasons.append("PCR unavailable")
    elif pcr >= 1.2:
        score += 2
        reasons.append(f"PCR {pcr:.2f} ≥ 1.20 — heavy put writing, supportive")
    elif pcr >= 1.0:
        score += 1
        reasons.append(f"PCR {pcr:.2f} ≥ 1.00 — put OI exceeds call OI")
    elif pcr <= 0.7:
        score -= 2
        reasons.append(f"PCR {pcr:.2f} ≤ 0.70 — heavy call writing, capping rallies")
    elif pcr <= 0.85:
        score -= 1
        reasons.append(f"PCR {pcr:.2f} ≤ 0.85 — call OI exceeds put OI")
    else:
        reasons.append(f"PCR {pcr:.2f} is balanced (0.85–1.00)")

    if vix is None:
        reasons.append("VIX unavailable")
    elif vix >= 22:
        score -= 1
        reasons.append(f"VIX {vix:.1f} ≥ 22 — fear elevated, discounts bullish reads")
    elif vix >= 18:
        reasons.append(f"VIX {vix:.1f} is elevated — wider ranges, richer premiums")
    elif vix <= 12:
        reasons.append(f"VIX {vix:.1f} is very low — thin premiums for sellers")
    else:
        reasons.append(f"VIX {vix:.1f} is moderate")

    label = "Bullish" if score >= 1 else "Bearish" if score <= -1 else "Neutral"
    return {"label": label, "score": score, "pcr": pcr, "vix": vix, "reasons": reasons}
