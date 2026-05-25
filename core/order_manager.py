import MetaTrader5 as mt5
import logging

logger = logging.getLogger("OrderManager")

class OrderManager:
    def __init__(self, magic_number: int):
        self.magic_number = magic_number
        self.active_trades = {}  # {order_ticket: {"sl": float, "tp": float, "strategy": str}}

    def add_trade(self, order_ticket: int, sl: float, tp: float, strategy_name: str):
        """Register a trade for tracking (called after successful execution)."""
        self.active_trades[order_ticket] = {
            "sl": sl,
            "tp": tp,
            "strategy": strategy_name
        }

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
    def execute_trade(self, symbol: str, order_type: str, lot: float, price: float = None, sl: float = None, tp: float = None, strategy_name: str = "", symbol_cache=None):
        sym_info = symbol_cache.get_info(symbol) if symbol_cache else mt5.symbol_info(symbol)
        tick = symbol_cache.get_tick(symbol) if symbol_cache else mt5.symbol_info_tick(symbol)
        if not sym_info or not tick: return False
        if price is None:
            price = tick.ask if 'BUY' in order_type else tick.bid
        stops_level = getattr(sym_info, 'stops_level', 0)
        point = getattr(sym_info, 'point', 0.00001)
        stop_level_dist = stops_level * point
        if tp:
            if order_type == 'BUY' and tp < price + stop_level_dist: tp = price + stop_level_dist + point
            elif order_type == 'SELL' and tp > price - stop_level_dist: tp = price - stop_level_dist - point
        if sl:
            if order_type == 'BUY' and sl > price - stop_level_dist: sl = price - stop_level_dist - point
            elif order_type == 'SELL' and sl < price + stop_level_dist: sl = price + stop_level_dist + point
        
        filling_mode = self._get_filling_mode(symbol, symbol_cache)
        
        # Handle Pending Orders & Expiration
        is_limit = ('LIMIT' in order_type.upper())
        is_stop = ('STOP' in order_type.upper())
        action = mt5.TRADE_ACTION_PENDING if (is_limit or is_stop) else mt5.TRADE_ACTION_DEAL
        
        # Determine MT5 order type
        if 'BUY' in order_type.upper():
            if is_limit: mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
            elif is_stop: mt5_type = mt5.ORDER_TYPE_BUY_STOP
            else: mt5_type = mt5.ORDER_TYPE_BUY
        else:
            if is_limit: mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
            elif is_stop: mt5_type = mt5.ORDER_TYPE_SELL_STOP
            else: mt5_type = mt5.ORDER_TYPE_SELL

        # PRICE SAFETY for Limits and Stops
        if is_limit:
            if mt5_type == mt5.ORDER_TYPE_BUY_LIMIT and price >= tick.ask:
                logger.warning(f"[{symbol}] Adjusting BUY_LIMIT: Price {price} is above/at Ask {tick.ask}. Using Ask - 1 pip.")
                price = tick.ask - (point * 10) # 1 pip buffer
            elif mt5_type == mt5.ORDER_TYPE_SELL_LIMIT and price <= tick.bid:
                logger.warning(f"[{symbol}] Adjusting SELL_LIMIT: Price {price} is below/at Bid {tick.bid}. Using Bid + 1 pip.")
                price = tick.bid + (point * 10)
        elif is_stop:
            if mt5_type == mt5.ORDER_TYPE_BUY_STOP and price <= tick.ask:
                logger.warning(f"[{symbol}] Adjusting BUY_STOP: Price {price} is below/at Ask {tick.ask}. Using Ask + 1 pip.")
                price = tick.ask + (point * 10)
            elif mt5_type == mt5.ORDER_TYPE_SELL_STOP and price >= tick.bid:
                logger.warning(f"[{symbol}] Adjusting SELL_STOP: Price {price} is above/at Bid {tick.bid}. Using Bid - 1 pip.")
                price = tick.bid - (point * 10)

        import time
        # Set expiration for pending orders (Default GTC - Good Til Cancelled)
        # Managing expirations manually via SPECIFIED can cause 10022 errors on some brokers.
        type_time = mt5.ORDER_TIME_GTC
        expiration = 0

        digits = getattr(sym_info, 'digits', 5)
        request = {
            "action": action, "symbol": symbol, "volume": float(lot),
            "type": mt5_type,
            "price": round(float(price), digits), 
            "sl": round(float(sl), digits) if sl else 0.0, 
            "tp": round(float(tp), digits) if tp else 0.0,
            "deviation": 30,
            "magic": self.magic_number, "comment": strategy_name[:31] if strategy_name else "Funded Sniper",
            "type_time": type_time, "type_filling": filling_mode,
        }
        if expiration > 0:
            request["expiration"] = expiration

        result = mt5.order_send(request)
        if result is None:
            logger.error(f"Order send failed for {symbol}: result is None. Error: {mt5.last_error()}")
            return None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed for {symbol}! Code: {result.retcode}, Comment: {result.comment}, Price: {price}")
            return result  # Return the result so caller can inspect retcode
        return result  # Return full OrderSendResult so caller can access .order, .price, etc.

    def close_position(self, position, symbol_cache=None):
        symbol = position.symbol
        tick = symbol_cache.get_tick(symbol) if symbol_cache else mt5.symbol_info_tick(symbol)
        if not tick: 
            logger.error(f"Failed to get tick for {symbol} while closing.")
            return False
        
        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": position.volume,
            "type": order_type,
            "position": position.ticket,
            "price": price,
            "deviation": 30,
            "magic": self.magic_number,
            "comment": "Close All (Guardian)",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol, symbol_cache),
        }
        
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error = mt5.last_error()
            logger.error(f"Failed to close position {position.ticket} for {symbol}. Code: {result.retcode if result else 'None'}, Error: {error}")
            return False
        
        logger.info(f"Successfully closed {symbol} position {position.ticket}")
        return True
