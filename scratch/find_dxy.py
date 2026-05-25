import MetaTrader5 as mt5

if mt5.initialize():
    symbols = mt5.symbols_get()
    print(f"Total symbols found: {len(symbols)}")
    dxy_likes = [s.name for s in symbols if "USD" in s.name or "DX" in s.name or "INDEX" in s.name.upper()]
    print("Potential DXY symbols:")
    for s in dxy_likes[:50]: # Print first 50
        print(f" - {s}")
    mt5.shutdown()
else:
    print("Failed to initialize MT5")
