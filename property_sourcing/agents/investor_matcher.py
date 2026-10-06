"""Investor-matcher agent — matches a sourced deal against your buyer/investor
CRM so outreach only ever goes to people who actually want that kind of
deal, in that area, at that budget. This is what keeps your sourcing fee
pipeline from becoming spam.
"""


def _area_matches(buyer_areas: list, lead_outcode: str) -> bool:
    if not buyer_areas:
        return True  # no area preference recorded = open to anything
    lead_outcode = (lead_outcode or "").upper()
    return any(lead_outcode.startswith(a.upper().strip()) for a in buyer_areas if a)


def _budget_matches(buyer: dict, asking_price) -> bool:
    if asking_price is None:
        return True
    lo = buyer.get("budget_min")
    hi = buyer.get("budget_max")
    if lo and asking_price < lo:
        return False
    if hi and asking_price > hi:
        return False
    return True


def _strategy_matches(buyer_strategies: list, lead_strategy: str) -> bool:
    if not buyer_strategies:
        return True
    if not lead_strategy:
        return True
    lead_strategy_lower = lead_strategy.lower()
    return any(s.lower() in lead_strategy_lower or lead_strategy_lower in s.lower() for s in buyer_strategies)


def _roi_matches(buyer: dict, roi_percent) -> bool:
    min_roi = buyer.get("min_roi_percent")
    if not min_roi or roi_percent is None:
        return True
    return roi_percent >= min_roi


def find_matching_buyers(lead: dict, buyers: list) -> list:
    """Returns the subset of `buyers` whose stated criteria fit this lead,
    best match first (simple scoring by how many criteria are explicitly set
    and satisfied, so a buyer with tight matching criteria that passes ranks
    higher than one who simply has no preferences recorded)."""
    matches = []
    for buyer in buyers:
        if not buyer.get("email"):
            continue
        area_ok = _area_matches(buyer.get("areas"), lead.get("outcode"))
        budget_ok = _budget_matches(buyer, lead.get("asking_price"))
        strategy_ok = _strategy_matches(buyer.get("strategies"), lead.get("strategy"))
        roi_ok = _roi_matches(buyer, lead.get("roi_percent"))

        if area_ok and budget_ok and strategy_ok and roi_ok:
            specificity = sum(
                1
                for v in (buyer.get("areas"), buyer.get("budget_max"), buyer.get("strategies"))
                if v
            )
            matches.append((specificity, buyer))

    matches.sort(key=lambda t: t[0], reverse=True)
    return [b for _, b in matches]
