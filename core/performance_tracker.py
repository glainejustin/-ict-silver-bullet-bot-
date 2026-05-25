import MetaTrader5 as mt5
from datetime import datetime
import pytz
import logging

logger = logging.getLogger("PerformanceTracker")

class PerformanceTracker:
    def __init__(self, magic_number: int, challenge_start_date: datetime):
        self.magic_number = magic_number
        self.challenge_start_date = challenge_start_date

    def _get_history_deals(self):
        """Fetch MT5 deal history since challenge start."""
        if self.challenge_start_date.tzinfo is None:
            self.challenge_start_date = pytz.UTC.localize(self.challenge_start_date)
            
        now = datetime.now(pytz.UTC)
        deals = mt5.history_deals_get(self.challenge_start_date, now)
        if deals is None:
            logger.error(f"Failed to fetch history deals. Error: {mt5.last_error()}")
            return []
        
        # Filter for closed deals with profit/loss (deal types: BUY/SELL), and matching magic
        # Usually MT5 deal entry is type deal, but profit is only on exit deals (deal.entry == DEAL_ENTRY_OUT)
        closed_deals = [d for d in deals if d.magic == self.magic_number and d.entry == mt5.DEAL_ENTRY_OUT]
        return closed_deals

    def _calculate_metrics(self, deals, limit=20):
        if not deals:
            return {
                'win_rate': 0.5,
                'expectancy': 0.0,
                'profit_factor': 1.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'count': 0
            }
            
        deals_sorted = sorted(deals, key=lambda d: d.time, reverse=True)
        recent_deals = deals_sorted[:limit]
        
        count = len(recent_deals)
        wins = [d.profit for d in recent_deals if d.profit > 0]
        losses = [abs(d.profit) for d in recent_deals if d.profit <= 0]
        
        win_rate = len(wins) / count if count > 0 else 0.5
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        # Expectancy = (Win% * Avg Win) - (Loss% * Avg Loss)
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        # Profit Factor = Gross Profit / Gross Loss
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

        return {
            'win_rate': win_rate,
            'expectancy': expectancy,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'count': count
        }

    def get_global_metrics(self, limit=50) -> dict:
        """Returns global performance metrics."""
        deals = self._get_history_deals()
        return self._calculate_metrics(deals, limit)

    def get_strategy_metrics(self, strategy_name: str, limit=20) -> dict:
        """Returns comprehensive metrics for a specific strategy."""
        deals = self._get_history_deals()
        strategy_deals = [d for d in deals if strategy_name in d.comment]
        return self._calculate_metrics(strategy_deals, limit)
