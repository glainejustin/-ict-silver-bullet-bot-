import MetaTrader5 as mt5
import logging
import pandas as pd
import numpy as np

class RiskManager:
    def __init__(self, account_balance: float):
        """
        Initializes the RiskManager with the current account balance.
        """
        self.account_balance = account_balance
        self.soft_recovery = False
        self.logger = logging.getLogger("RiskManager")

    def calculate_lot_size(self, symbol: str, sl_price: float, order_type: str, risk_percent: float = None, entry_price: float = None, symbol_cache=None, alert_manager=None) -> float:
        """
        Calculates the lot size based on a fixed percentage risk of the account balance.
        """
        # Always update account balance from MT5 before calculating
        acc = mt5.account_info()
        if acc:
            self.account_balance = acc.balance  # Use balance to avoid over-leveraging

        if risk_percent is None:
            import config
            risk_percent = config.RISK_PERCENT / 100.0
            
        # Soft Recovery halves the risk if active (e.g., after a losing day)
        if self.soft_recovery:
            risk_percent = risk_percent / 2.0

        # Coast Mode: Reduce risk near target
        acc = mt5.account_info()
        if acc:
            import config
            # Use challenge_start_balance if we had it, but for now we calculate vs current balance
            # Better: RiskManager should be aware of challenge_start_balance. 
            # For simplicity here, we assume 5000 is base.
            base = getattr(self, 'challenge_start_balance', 5000.0) 
            current_profit_pct = ((acc.equity / base) - 1) * 100
            if current_profit_pct >= getattr(config, 'COAST_MODE_THRESHOLD', 7.0):
                risk_percent = getattr(config, 'COAST_MODE_RISK', 0.1) / 100.0
                self.logger.info(f"COAST MODE ACTIVE: Risk capped at {risk_percent:.2%}")

        if symbol_cache:
            tick = symbol_cache.get_tick(symbol)
            symbol_info = symbol_cache.get_info(symbol)
        else:
            tick = mt5.symbol_info_tick(symbol)
            symbol_info = mt5.symbol_info(symbol)

        if not tick or not symbol_info:
            return 0.0
            
        if entry_price is None:
            entry_price = tick.ask if 'BUY' in order_type.upper() else tick.bid
            
        sl_distance = abs(entry_price - sl_price)
        
        if sl_distance == 0:
            return 0.0

        # Risk amount in account currency (e.g. USD)
        risk_amount = self.account_balance * risk_percent
        
        # Safe lot size calculation using tick value (handles JPY/non-USD pairs)
        tick_size = symbol_info.trade_tick_size
        tick_value = symbol_info.trade_tick_value
        
        if tick_size == 0 or tick_value == 0:
            self.logger.error(f"[{symbol}] Invalid tick data. size: {tick_size}, value: {tick_value}")
            return 0.0
            
        sl_distance_ticks = sl_distance / tick_size
        loss_per_lot = sl_distance_ticks * tick_value
        
        if loss_per_lot == 0:
            return 0.0
            
        lot_size = risk_amount / loss_per_lot
        
        # Round lot size to volume_step
        step = symbol_info.volume_step
        if step > 0:
            lot_size = round(lot_size / step) * step
        
        # Ensure lot size is within symbol limits, but REJECT if it exceeds risk
        if lot_size < symbol_info.volume_min:
            actual_risk = (symbol_info.volume_min * loss_per_lot) / self.account_balance * 100
            if actual_risk > (risk_percent * 100 * 1.5): # If actual risk is 50% larger than intended, block it
                msg = f"🚫 <b>TRADE BLOCKED</b>\n[{symbol}] Min lot {symbol_info.volume_min} causes {actual_risk:.2f}% risk (Limit: {risk_percent*100:.2f}%). SL too wide."
                self.logger.warning(f"TRADE BLOCKED | [{symbol}] Min lot causes {actual_risk:.2f}% risk. Limit {risk_percent*100:.2f}%.")
                if alert_manager:
                    alert_manager.send_message(msg)
                return 0.0 # Block trade
            
            # Allow slight override if within 1.5x of risk
            self.logger.warning(f"MIN LOT OVERRIDE | [{symbol}] Using {symbol_info.volume_min}. Actual Risk: {actual_risk:.2f}%")
            lot_size = symbol_info.volume_min
            
        # Volatility Adjustment (Institutional Hardening)
        import config
        if getattr(config, 'ATR_VOLATILITY_ADJUSTMENT', False):
            try:
                # Calculate current vs average volatility
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, config.VOLATILITY_EMA_PERIOD + 1)
                if rates is not None and len(rates) >= config.VOLATILITY_EMA_PERIOD:
                    df = pd.DataFrame(rates)
                    df['tr'] = np.maximum(df['high'] - df['low'], 
                                np.maximum(abs(df['high'] - df['close'].shift(1)), 
                                            abs(df['low'] - df['close'].shift(1))))
                    avg_vol = df['tr'].iloc[-config.VOLATILITY_EMA_PERIOD-1:-1].mean()
                    curr_vol = df['tr'].iloc[-1]
                    
                    if avg_vol > 0:
                        vol_ratio = curr_vol / avg_vol
                        if vol_ratio > config.VOLATILITY_THRESHOLD:
                            # Reduce risk by the inverse of the excess volatility
                            penalty = config.VOLATILITY_THRESHOLD / vol_ratio
                            lot_size = lot_size * penalty
                            self.logger.info(f"VOLATILITY PENALTY | [{symbol}] Ratio: {vol_ratio:.2f}x | Penalty: {penalty:.2f}x | New Lot: {lot_size:.2f}")
            except Exception as e:
                self.logger.error(f"Error calculating Vol-Adjustment: {e}")

        # 4. Correlation Multiplier (Institutional Portfolio Management)
        import config
        active_positions = mt5.positions_get(magic=config.MAGIC_NUMBER)
        if active_positions:
            for group in getattr(config, 'CORRELATION_GROUPS', []):
                if symbol in group:
                    # Check if we already have a position in this group
                    other_symbols = [s for s in group if s != symbol]
                    if any(p.symbol in other_symbols for p in active_positions):
                        self.logger.info(f"CORRELATION PENALTY | [{symbol}] Active sibling in group {group}. Halving risk.")
                        lot_size = lot_size * 0.5
                        break

        # 5. Execution Tax (Quant Research Hardening)
        # Scale down if market velocity (TPS) is dangerously high
        current_tps = symbol_cache.get_tps(symbol) if (symbol_cache and hasattr(symbol_cache, 'get_tps')) else 0.0
        if current_tps > 30:
            self.logger.info(f"EXECUTION TAX | [{symbol}] High Velocity: {current_tps:.1f} ticks/sec. Scaling lot size by 0.8x.")
            lot_size = lot_size * 0.8

        # 6. "House Money" Logic (Trading Psychology Hardening)
        # If we are already up for the day, reduce risk to protect the daily win
        if 'day_start_equity' in locals() or hasattr(self, 'day_start_equity'):
            d_equity = getattr(self, 'day_start_equity', self.account_balance)
            daily_profit_pct = ((self.account_balance - d_equity) / d_equity) * 100 if d_equity > 0 else 0
            if daily_profit_pct >= getattr(config, 'DAILY_GOAL_PERCENT', 1.5):
                self.logger.info(f"HOUSE MONEY MODE | [{symbol}] Daily Profit: {daily_profit_pct:.2f}%. Scaling risk by 0.5x to protect gains.")
                lot_size = lot_size * 0.5

        lot_size = min(symbol_info.volume_max, lot_size)
        return float(round(lot_size, 2))
