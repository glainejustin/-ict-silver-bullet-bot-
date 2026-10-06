"""Rental-matching agent — pairs tenant leads with available rental listings
by area, budget and bedroom requirement. Mirrors the logic in
investor_matcher.py but for the lettings side of the business.
"""


def _area_matches(tenant_areas: list, listing_outcode: str) -> bool:
    if not tenant_areas:
        return True
    listing_outcode = (listing_outcode or "").upper()
    return any(listing_outcode.startswith(a.upper().strip()) for a in tenant_areas if a)


def _budget_matches(tenant: dict, monthly_rent) -> bool:
    if monthly_rent is None:
        return True
    budget_max = tenant.get("budget_max")
    if budget_max and monthly_rent > budget_max:
        return False
    return True


def _bedrooms_match(tenant: dict, listing_bedrooms) -> bool:
    needed = tenant.get("bedrooms_needed")
    if not needed or listing_bedrooms is None:
        return True
    return listing_bedrooms >= needed


def find_matching_tenants(listing: dict, tenants: list) -> list:
    """Returns tenants (best match first) whose stated criteria fit this
    rental listing."""
    matches = []
    for tenant in tenants:
        if not tenant.get("email"):
            continue
        if tenant.get("status") not in (None, "new", "matched"):
            continue  # skip tenants already placed/inactive

        area_ok = _area_matches(tenant.get("areas"), listing.get("outcode"))
        budget_ok = _budget_matches(tenant, listing.get("monthly_rent"))
        bedrooms_ok = _bedrooms_match(tenant, listing.get("bedrooms"))

        if area_ok and budget_ok and bedrooms_ok:
            specificity = sum(1 for v in (tenant.get("areas"), tenant.get("budget_max"), tenant.get("bedrooms_needed")) if v)
            matches.append((specificity, tenant))

    matches.sort(key=lambda t: t[0], reverse=True)
    return [t for _, t in matches]
