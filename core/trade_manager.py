import MetaTrader5 as mt5
import config
import logging

logger = logging.getLogger("TradeManager")

class TradeManager:
    def __init__(self, magic_number: int, initial_risks: dict = None, partial_done: set = None, breakeven_done: set = None):
        self.magic_number = magic_number
        self.partial_done = set(partial_done) if partial_done else set()
        self.breakeven_done = set(breakeven_done) if breakeven_done else set()
        self.initial_risks = initial_risks if initial_risks else {} # Stores {ticket: initial_risk_pips}

    def _get_filling_mode(self, symbol, symbol_cache=None):
        sym_info = symbol_cache.get_info(symbol) if symbol_cache else mt5.symbol_info(symbol)
        if not sym_info:
            return mt5.ORDER_FILLING_FOK
        filling_mode = sym_info.filling_mode
        if filling_mode & 1:
            return mt5.ORDER_FILLING_FOK
        elif filling_mode & 2:
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN

    def manage_open_positions(self, symbol: str, symbol_cache=None):
        for t in list(self.partial_done):
            if not mt5.positions_get(ticket=t):
                self.partial_done.discard(t)
                self.breakeven_done.discard(t)
                self.initial_risks.pop(t, None)

        positions = mt5.positions_get(symbol=symbol)
        if not positions: return

        sym_info = symbol_cache.get_info(symbol) if symbol_cache else mt5.symbol_info(symbol)
        if not sym_info: return
        pip_size = config.SYMBOL_PIP_SIZE.get(symbol, 0.0001)

        for pos in positions:
            if pos.magic != self.magic_number: continue
            ticket = pos.ticket
            entry_price = pos.price_open
            pos_type = pos.type
            volume = pos.volume
            tick = symbol_cache.get_tick(symbol) if symbol_cache else mt5.symbol_info_tick(symbol)
            if not tick: continue
            current_price = tick.bid if pos_type == 0 else tick.ask
            # Store initial risk pips if not already stored
            if ticket not in self.initial_risks:
                self.initial_risks[ticket] = abs(entry_price - pos.sl) / pip_size
            
            initial_risk_pips = self.initial_risks[ticket]
            if initial_risk_pips == 0: continue
            current_profit_pips = (current_price - entry_price) / pip_size if pos_type == 0 else (entry_price - current_price) / pip_size
            current_rr = current_profit_pips / initial_risk_pips
            is_be = ticket in self.breakeven_done
            has_taken_partial = ticket in self.partial_done

            if current_rr >= config.PARTIAL_TP_RR and not has_taken_partial:
                 close_vol = round(volume * config.PARTIAL_TP_PCT / sym_info.volume_step) * sym_info.volume_step
                 if close_vol >= sym_info.volume_min:
                     # Check if remaining volume would be valid
                     if (volume - close_vol) < sym_info.volume_min:
                         logger.info(f"[{symbol}] Partial TP would leave invalid volume. Closing full position.")
                         mt5.Close(symbol, ticket=ticket)
                         self.partial_done.add(ticket)
                         continue
                         
                     logger.info(f"[{symbol}] Partial TP ({close_vol} lots).")
                     self.close_partial(pos, close_vol, symbol_cache)
                     self.partial_done.add(ticket)
                     self.modify_sl(ticket, entry_price, pos.tp)
                     self.breakeven_done.add(ticket)
                     continue

            if current_rr >= config.BREAKEVEN_RR and not is_be:
                is_safe = (pos_type == 0 and current_price > entry_price) or (pos_type == 1 and current_price < entry_price)
                if is_safe:
                    logger.info(f"[{symbol}] Moving SL to Breakeven.")
                    self.modify_sl(ticket, entry_price, pos.tp)
                    self.breakeven_done.add(ticket)

            if current_rr >= 1.0:
                import numpy as np
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 15)
                if rates is not None and len(rates) > 1:
                    tr = np.maximum(rates['high'][1:] - rates['low'][1:], 
                                    np.maximum(np.abs(rates['high'][1:] - rates['close'][:-1]), 
                                               np.abs(rates['low'][1:] - rates['close'][:-1])))
                    atr = np.mean(tr)
                else:
                    atr = initial_risk_pips * pip_size
                
                if current_rr >= 2.0:
                    trail_dist = atr * 1.5
                else:
                    trail_dist = atr * 2.5
                    
                if pos_type == 0:
                    new_sl = current_price - trail_dist
                    if new_sl < entry_price: continue # Guard: Never trail below entry
                    if new_sl > pos.sl + (pip_size * 5): self.modify_sl(ticket, new_sl, pos.tp)
                else:
                    new_sl = current_price + trail_dist
                    if new_sl > entry_price: continue # Guard: Never trail above entry
                    if new_sl < pos.sl - (pip_size * 5): self.modify_sl(ticket, new_sl, pos.tp)

    def close_partial(self, pos, volume: float, symbol_cache=None):
        tick = symbol_cache.get_tick(pos.symbol) if symbol_cache else mt5.symbol_info_tick(pos.symbol)
        price = tick.bid if pos.type == 0 else tick.ask
        filling_mode = self._get_filling_mode(pos.symbol, symbol_cache)
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "position": pos.ticket, "symbol": pos.symbol,
            "volume": float(volume), "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
            "price": float(price), "magic": self.magic_number, "comment": "Partial TP",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_mode,
        }
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE: logger.error(f"Partial failed: {result.comment}")

    def modify_sl(self, ticket: int, sl: float, tp: float) -> bool:
        request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": float(sl), "tp": float(tp)}
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE: return False
        return True

    def get_state(self):
        """Returns the current trade management state for persistence."""
        return {
            "initial_risks": {str(k): v for k, v in self.initial_risks.items()},
            "partial_done": list(self.partial_done),
            "breakeven_done": list(self.breakeven_done)
        }
