"""Common interface every data connector implements.

A connector's only job is to find *signals* of a potential deal and return
them as plain dicts matching the `leads` table shape. It should NOT do
valuation or outreach — that's the agents' job. This separation is what lets
you add a new free data source later without touching anything else.
"""
from abc import ABC, abstractmethod


class BaseConnector(ABC):
    name = "base"

    @abstractmethod
    def fetch_leads(self) -> list:
        """Return a list of dicts shaped like:
        {
          "source": "land_registry" | "companies_house" | "auction" | "csv_import",
          "source_ref": "<unique id so we never duplicate the same lead>",
          "address": str,
          "postcode": str,
          "outcode": str,
          "property_type": "flat" | "terraced" | "semi" | "detached" | "other",
          "bedrooms": int | None,
          "asking_price": float | None,
          "motivation_signal": str,   # why this is a potential lead
          "raw_data": dict,           # anything else worth keeping
        }
        """
        raise NotImplementedError

    @staticmethod
    def normalise_postcode(postcode: str) -> str:
        return (postcode or "").strip().upper()

    @staticmethod
    def outcode_of(postcode: str) -> str:
        postcode = (postcode or "").strip().upper()
        return postcode.split(" ")[0] if postcode else ""
