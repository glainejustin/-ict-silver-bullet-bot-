"""Generic public auction-catalogue feed connector.

Many UK property auction houses publish their current lots as a public
RSS/Atom feed for marketing purposes (that's the whole point of an auction
catalogue — to be seen). This connector will poll any feed URLs *you* add to
AUCTION_FEED_URLS after checking that site's terms of use allow automated
polling. It never touches Rightmove/Zoopla or any portal whose terms
prohibit scraping.

Auction properties are a great source of genuinely below-market-value deals
because guide prices are usually set to attract bidders.
"""
import logging
import re

import feedparser

import config
from connectors.base import BaseConnector

logger = logging.getLogger(__name__)

PRICE_RE = re.compile(r"£\s?([\d,]+)")


class AuctionFeedConnector(BaseConnector):
    name = "auction"

    def __init__(self, feed_urls: list = None):
        self.feed_urls = feed_urls if feed_urls is not None else config.AUCTION_FEED_URLS

    @staticmethod
    def _extract_price(text: str):
        if not text:
            return None
        match = PRICE_RE.search(text)
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _extract_postcode(text: str):
        if not text:
            return ""
        # Simple UK postcode pattern, good enough for free-text auction titles.
        match = re.search(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", text.upper())
        return match.group(0) if match else ""

    def fetch_leads(self) -> list:
        if not self.feed_urls:
            logger.info("No AUCTION_FEED_URLS configured — skipping auction connector.")
            return []

        leads = []
        for url in self.feed_urls:
            try:
                parsed = feedparser.parse(url)
            except Exception as exc:  # feedparser swallows most errors internally anyway
                logger.warning("Failed to parse auction feed %s: %s", url, exc)
                continue

            for entry in parsed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                postcode = self._extract_postcode(title) or self._extract_postcode(summary)
                leads.append(
                    {
                        "source": self.name,
                        "source_ref": entry.get("id") or entry.get("link"),
                        "address": title,
                        "postcode": postcode,
                        "outcode": self.outcode_of(postcode),
                        "property_type": None,
                        "bedrooms": None,
                        "asking_price": self._extract_price(title) or self._extract_price(summary),
                        "motivation_signal": "Listed for auction — guide price, seller wants a quick sale.",
                        "raw_data": {"link": entry.get("link"), "summary": summary},
                    }
                )
        return leads
