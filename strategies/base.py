from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any
import pandas as pd
import config

class Strategy(ABC):
    """
    Abstract Base Class for all trading strategies.
    
    All strategies must implement the generate_signal method to be compatible
    with the SignalAggregator.
    """
    
    def __init__(self, name: str, symbol: str, weight: float = 1.0):
        """
        Initializes the strategy.
        
        Args:
            name: Human-readable name of the strategy.
            symbol: The target symbol this instance is responsible for.
            weight: The weight assigned to this strategy's signals (default 1.0).
        """
        self.name = name
        self.symbol = symbol
        self.weight = weight
        self.enabled = True

    def check_volume(self, data: pd.DataFrame) -> bool:
        """
        Checks if the current volume is above average.
        """
        if 'tick_volume' not in data.columns:
            return True # Fallback if volume not available
            
        try:
            vol_series = pd.to_numeric(data['tick_volume'], errors='coerce').fillna(0)
            avg_vol = vol_series.tail(config.VOL_MA_PERIOD).mean()
            last_vol = vol_series.iloc[-1]
            return last_vol >= avg_vol
        except Exception:
            return True

    @abstractmethod
    def generate_signal(self, data_ltf: pd.DataFrame, data_htf: pd.DataFrame, data_struct: pd.DataFrame, current_time: datetime) -> Dict[str, Any]:
        """
        Analyzes triple-timeframe market data and generates a trading signal.
        
        Args:
            data_ltf: Lower timeframe data (e.g. M1) for entry.
            data_htf: Higher timeframe data (e.g. H1) for trend.
            data_struct: Structural timeframe data (e.g. H4) for levels.
            current_time: The current market time.
        """
        pass
