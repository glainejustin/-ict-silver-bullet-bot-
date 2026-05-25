import json
import urllib.request
import ssl
from datetime import datetime, timedelta
import pytz
import logging
import os

logger = logging.getLogger("NewsManager")

class NewsManager:
    def __init__(self, cache_file="news_cache.json"):
        self.cache_file = cache_file
        self.events = []
        self.last_fetch = None
        self.load_cache()

    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    data = json.load(f)
                    self.events = data.get("events", [])
                    if "last_fetch" in data:
                        self.last_fetch = datetime.fromisoformat(data["last_fetch"])
            except Exception as e:
                logger.error(f"Error loading news cache: {e}")

    def save_cache(self):
        try:
            with open(self.cache_file, "w") as f:
                json.dump({
                    "events": self.events,
                    "last_fetch": self.last_fetch.isoformat() if self.last_fetch else None
                }, f)
        except Exception as e:
            logger.error(f"Error saving news cache: {e}")

    def fetch_news(self):
        # Only fetch if we don't have events or it's been more than 12 hours
        if self.last_fetch and datetime.now(pytz.UTC) - self.last_fetch < timedelta(hours=12) and self.events:
            return

        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            # Use unverified SSL context to avoid VPS certificate issues
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ctx) as response:
                data = json.loads(response.read().decode())
                
                # Filter for High impact events
                high_impact = []
                for event in data:
                    if event.get("impact") == "High":
                        high_impact.append({
                            "title": event.get("title"),
                            "country": event.get("country"),
                            "date": event.get("date")
                        })
                
                self.events = high_impact
                self.last_fetch = datetime.now(pytz.UTC)
                self.save_cache()
                logger.info(f"Fetched {len(high_impact)} high-impact news events.")
        except Exception as e:
            logger.error(f"Failed to fetch news: {e}")
            # Set last_fetch anyway to prevent retry spam every cycle
            self.last_fetch = datetime.now(pytz.UTC)

    def is_news_window(self, symbol: str, current_time: datetime, buffer_minutes: int) -> bool:
        """
        Returns True if current_time is within buffer_minutes of a High impact event for the symbol.
        """
        self.fetch_news()
        if not self.events: return False

        # Extract currencies from symbol (e.g., EURUSD -> EUR, USD)
        currencies = [symbol[:3], symbol[3:6]]
        if "XAU" in currencies: currencies.append("USD") # Gold responds to USD news

        for event in self.events:
            if event["country"] not in currencies: continue
            
            try:
                # Parse event date (timezone aware)
                event_time = datetime.fromisoformat(event["date"])
                # Convert to UTC if it's not
                event_time = event_time.astimezone(pytz.UTC)
                
                time_diff = abs((current_time - event_time).total_seconds()) / 60
                
                if time_diff <= buffer_minutes:
                    logger.info(f"[{symbol}] News Window Active: {event['title']} for {event['country']}")
                    return True
            except Exception as e:
                pass # Ignore parsing errors on individual events

        return False
