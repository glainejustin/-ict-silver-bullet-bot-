import MetaTrader5 as mt5
import sys
import os

# Ensure the root directory is in the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.connection import MT5Connection
from core.order_manager import OrderManager
import config

def run_test_trade():
    print("--- Starting Manual Test Trade ---")
    
    # 1. Connect
    conn = MT5Connection()
    if not conn.connect():
        print("Failed to connect to MT5.")
        return

    # 2. Setup Managers
    order_manager = OrderManager(magic_number=123456) # Unique magic for test
    symbol = "EURUSD"
    
    # 3. Get Price
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"Could not get tick for {symbol}. Make sure it is in your Market Watch.")
        return
        
    price = tick.ask
    sl = price - (0.0001 * 50) # 50 pips SL
    tp = price + (0.0001 * 100) # 100 pips TP
    lot = 0.01
    
    print(f"Attempting to BUY {lot} lots of {symbol} at {price}...")
    print(f"SL: {sl} | TP: {tp}")

    # 4. Execute
    success = order_manager.execute_trade(
        symbol=symbol,
        order_type='BUY',
        lot=lot,
        sl=sl,
        tp=tp
    )
    
    if success:
        print("\nSUCCESS! Check your MT5 terminal for the open order.")
    else:
        error = mt5.last_error()
        print(f"\nFAILED. MT5 Error: {error}")
        # Try to get more detail if possible
        print(f"Check your terminal for retcode details.")

    # Shutdown
    mt5.shutdown()

if __name__ == "__main__":
    run_test_trade()
