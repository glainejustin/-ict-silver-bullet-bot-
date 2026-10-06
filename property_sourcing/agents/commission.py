"""Commission calculation for the lettings referral model.

By design, this module only ever calculates a fee charged to the LANDLORD.
There is deliberately no code path here that charges a tenant anything —
see docs/LETTINGS_LEGAL_COMPLIANCE.md for why that's a hard legal line
under the Tenant Fees Act 2019, not just a preference.
"""
import config

VALID_TYPES = {"one_month_rent", "percent_of_annual_rent", "flat_fee"}


def calculate_commission(monthly_rent: float) -> float:
    """Returns the commission owed by the landlord for a successful let,
    based on COMMISSION_TYPE / COMMISSION_VALUE in config (.env)."""
    if not monthly_rent:
        return 0.0

    commission_type = config.COMMISSION_TYPE
    value = config.COMMISSION_VALUE

    if commission_type == "percent_of_annual_rent":
        return round(monthly_rent * 12 * (value / 100), 2)
    if commission_type == "flat_fee":
        return round(value, 2)
    # default / "one_month_rent"
    return round(monthly_rent * value, 2)


def describe_commission_terms() -> str:
    commission_type = config.COMMISSION_TYPE
    value = config.COMMISSION_VALUE
    if commission_type == "percent_of_annual_rent":
        return f"{value}% of the first year's rent"
    if commission_type == "flat_fee":
        return f"a flat fee of £{value:,.0f}"
    multiplier = "one month's" if value == 1 else f"{value}x month's"
    return f"{multiplier} rent"
