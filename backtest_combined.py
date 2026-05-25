import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import os
import requests
import json

# Strategies
from strategies.base import Strategy
from strategies.raja_banks import RajaBanksStrategy
from strategies.london_breakout import LondonBreakoutStrategy
from strategies.silver_bullet import SilverBulletStrategy
from strategies.pure_price_action import PurePriceActionStrategy
from core.price_action import PriceAction
from core.sentiment_manager import SentimentManager
import config

class MultiBacktester:
    def __init__(self, initial_balance: float = 5000.0, profit_target_pct: float = None, loss_limit_pct: float = None):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.profit_target_pct = profit_target_pct if profit_target_pct is not None else config.OVERALL_PROFIT_TARGET_PERCENT
        self.loss_limit_pct = loss_limit_pct if loss_limit_pct is not None else config.MAX_TOTAL_LOSS_PERCENT
        self.total_equity = [initial_balance]
        self.trades = []
        self.strategy_pnl = {}
        self.symbol_data = {}
        self.strategies = {}
        self.months = 3

    def fetch_all_data(self, months: int = 3):
        if not mt5.initialize():
            print(f"MT5 initialization failed: {mt5.last_error()}")
            return False
        self.months = months
        lookback_mins = int(months * 30 * 24 * 60)
        for symbol in config.SYMBOLS:
            print(f"Fetching synced data for {symbol}...")
            self.symbol_data[symbol] = {
                'm1': self._get_rates(symbol, mt5.TIMEFRAME_M1, lookback_mins),
                'm5': self._get_rates(symbol, mt5.TIMEFRAME_M5, lookback_mins // 5),
                'h1': self._get_rates(symbol, mt5.TIMEFRAME_H1, lookback_mins // 60),
                'h4': self._get_rates(symbol, mt5.TIMEFRAME_H4, lookback_mins // 240)
            }
            strat_names = config.SYMBOL_STRATEGY_MAP.get(symbol, [])
            self.strategies[symbol] = []
            for s_name in strat_names:
                if s_name == "RajaBanksStrategy":
                    self.strategies[symbol].append(RajaBanksStrategy(f"Raja_{symbol}", symbol))
                elif s_name == "LondonBreakoutStrategy":
                    self.strategies[symbol].append(LondonBreakoutStrategy(f"London_{symbol}", symbol))
                elif s_name == "SilverBulletStrategy":
                    self.strategies[symbol].append(SilverBulletStrategy(f"Silver_{symbol}", symbol))
                elif s_name == "PurePriceActionStrategy":
                    self.strategies[symbol].append(PurePriceActionStrategy(f"PurePA_{symbol}", symbol))
        return True

    def _get_rates(self, symbol, timeframe, count):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + 200)
        if rates is None: return pd.DataFrame()
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True, drop=False)
        return df

    def run_combined(self):
        print(f"Starting Challenge-Aware Simulation ({self.profit_target_pct}% Target / {self.loss_limit_pct}% Loss)...")
        
        # Build a global sorted timeline from all symbols
        all_times = set()
        for sym, data in self.symbol_data.items():
            if not data['m5'].empty:
                all_times.update(data['m5'].index)
        
        master_timeline = sorted(list(all_times))
        if not master_timeline:
            print("No data available for backtest.")
            return

        active_trades = []
        
        current_day = None
        day_start_equity = self.balance
        halt_trading_for_day = False
        daily_trade_count = 0

        for current_time in master_timeline:
            # 0. Overall Challenge Halt Check (Sync with main.py Guardian)
            total_pnl_pct = ((self.balance) / self.initial_balance - 1) * 100
            if total_pnl_pct >= self.profit_target_pct:
                print(f"CHALLENGE PASSED at {current_time}! Target {self.profit_target_pct}% reached.")
                break
            if total_pnl_pct <= -self.loss_limit_pct:
                print(f"CHALLENGE FAILED at {current_time}! Max Loss {self.loss_limit_pct}% reached.")
                break

            # 1. Day Reset
            if current_day != current_time.date():
                current_day = current_time.date()
                
                # 1b. Equity-Aware Day Start (Fix for carried-over floating PnL)
                unrealized_pnl_carry = 0
                for trade in active_trades:
                    sym = trade['symbol']
                    df_sym = self.symbol_data[sym]['m5']
                    if current_time in df_sym.index:
                        cp = df_sym.loc[current_time]['close']
                    else:
                        # Realistic Fix
                        idx = df_sym.index.searchsorted(current_time, side='right') - 1
                        cp = df_sym.iloc[idx]['close'] if idx >= 0 else trade['entry_price']

                    if trade['type'] == 'BUY':
                        unrealized_pnl_carry += (cp - trade['entry_price']) * trade['contract_size'] * trade['lot_size']
                    else:
                        unrealized_pnl_carry += (trade['entry_price'] - cp) * trade['contract_size'] * trade['lot_size']
                
                day_start_equity = self.balance + unrealized_pnl_carry
                halt_trading_for_day = False
                daily_trade_count = 0

            # 2. Equity-Based Daily Limit Check (Funded Guardian Logic)
            unrealized_pnl = 0
            for trade in active_trades:
                symbol = trade['symbol']
                df_sym = self.symbol_data[symbol]['m5']
                if current_time in df_sym.index:
                    current_price = df_sym.loc[current_time]['close']
                else:
                    # Realistic Fix: Use most recent close before this timestamp
                    idx = df_sym.index.searchsorted(current_time, side='right') - 1
                    if idx >= 0:
                        current_price = df_sym.iloc[idx]['close']
                    else:
                        current_price = trade['entry_price'] # Fallback
                
                if trade['type'] == 'BUY':
                    pnl = (current_price - trade['entry_price']) * trade['contract_size'] * trade['lot_size']
                else:
                    pnl = (trade['entry_price'] - current_price) * trade['contract_size'] * trade['lot_size']
                unrealized_pnl += pnl
            
            current_equity = self.balance + unrealized_pnl
            profit_pct = ((current_equity - day_start_equity) / day_start_equity) * 100 if day_start_equity > 0 else 0
            
            # 2c. Daily Profit Cap / Loss Limit
            daily_pnl_pct = ((current_equity - day_start_equity) / day_start_equity) * 100 if day_start_equity > 0 else 0
            if daily_pnl_pct >= config.DAILY_GOAL_PERCENT or daily_pnl_pct <= -config.MAX_DAILY_LOSS_PERCENT:
                if not halt_trading_for_day:
                    halt_trading_for_day = True
                    # Close trades
                    for trade in active_trades[:]:
                        symbol = trade['symbol']
                        candle = self.symbol_data[symbol]['m5'].loc[current_time]
                        self._close_trade(trade, candle['close'], current_time)
                        active_trades.remove(trade)
                continue
            
            # 2b. Friday Close Guard
            if current_time.weekday() == 4 and current_time.hour >= config.FRIDAY_CLOSE_HOUR:
                if active_trades:
                    print(f"Friday {config.FRIDAY_CLOSE_HOUR}:00 reached. Closing all for weekend.")
                    for trade in active_trades[:]:
                        symbol = trade['symbol']
                        candle = self.symbol_data[symbol]['m5'].loc[current_time]
                        self._close_trade(trade, candle['close'], current_time)
                        active_trades.remove(trade)
                continue

            # 3. Precise Exit Logic (M1 Tick Validation)
            for trade in active_trades[:]:
                symbol = trade['symbol']
                df_m1 = self.symbol_data[symbol]['m1']
                
                # Use searchsorted for robust tz-agnostic slicing
                ct_val = current_time
                ct_end_val = current_time + timedelta(minutes=5)
                start_i = df_m1.index.searchsorted(ct_val)
                end_i = df_m1.index.searchsorted(ct_end_val)
                exit_m1_window = df_m1.iloc[start_i:end_i]
                
                if exit_m1_window.empty:
                    # Fallback to M5 if M1 missing (less accurate)
                    df_m5 = self.symbol_data[symbol]['m5']
                    ct_ts = pd.Timestamp(current_time)
                    if ct_ts not in df_m5.index:
                        idx = df_m5.index.searchsorted(ct_ts, side='right') - 1
                        candle = df_m5.iloc[idx] if idx >= 0 else None
                    else:
                        candle = df_m5.loc[ct_ts]
                    if candle is None:
                        continue
                    if trade['type'] == 'BUY':
                        if candle['low'] <= trade['sl']: self._close_trade(trade, trade['sl'], current_time); active_trades.remove(trade)
                        elif candle['high'] >= trade['tp']: self._close_trade(trade, trade['tp'], current_time); active_trades.remove(trade)
                    else:
                        if candle['high'] >= trade['sl']: self._close_trade(trade, trade['sl'], current_time); active_trades.remove(trade)
                        elif candle['low'] <= trade['tp']: self._close_trade(trade, trade['tp'], current_time); active_trades.remove(trade)
                    continue

                for m1_time, m1_bar in exit_m1_window.iterrows():
                    exit_price = None
                    if trade['type'] == 'BUY':
                        # Pessimistic: Check SL first within M1 bar
                        if m1_bar['low'] <= trade['sl']: exit_price = trade['sl']
                        elif m1_bar['high'] >= trade['tp']: exit_price = trade['tp']
                    else:
                        if m1_bar['high'] >= trade['sl']: exit_price = trade['sl']
                        elif m1_bar['low'] <= trade['tp']: exit_price = trade['tp']
                    
                    if exit_price:
                        self._close_trade(trade, exit_price, m1_time)
                        active_trades.remove(trade)
                        break

            # 4. Entry Logic (Only if not halted)
            if not halt_trading_for_day and daily_trade_count < config.MAX_DAILY_TRADES:
                for symbol in config.SYMBOLS:
                    if any(t['symbol'] == symbol for t in active_trades): continue
                    if current_time not in self.symbol_data[symbol]['m5'].index: continue
                    
                    df_m5 = self.symbol_data[symbol]['m5']
                    idx = df_m5.index.get_loc(current_time)
                    if idx < 100: continue
                    
                    m5_slice = df_m5.iloc[idx-100:idx]
                    h1_full = self.symbol_data[symbol]['h1']
                    h1_slice = h1_full[h1_full['time'] < current_time].tail(50)
                    h4_full = self.symbol_data[symbol]['h4']
                    h4_slice = h4_full[h4_full['time'] < current_time].tail(50)
                    
                    sentiment_manager = SentimentManager() # Local instance for state-free check
                    
                    # Aggregate signals from all strategies for this symbol
                    strat_signals = []
                    for strat in self.strategies[symbol]:
                        res = strat.generate_signal(m5_slice, h1_slice, h4_slice, current_time)
                        if res['signal'] != 'HOLD':
                            # H4 Bias Filter
                            last_h4 = h4_slice.iloc[-1]
                            h4_bias = "BULLISH" if last_h4['close'] > last_h4['open'] else "BEARISH"
                            if (res['signal'] == 'BUY' and h4_bias != "BULLISH") or \
                               (res['signal'] == 'SELL' and h4_bias != "BEARISH"):
                                continue
                            strat_signals.append(res)
                    
                    if not strat_signals:
                        continue
                    
                    # Pick first valid signal (matching SignalAggregator logic)
                    res = None
                    for s in strat_signals:
                        if s.get('confidence', 1.0) >= 1.0: # Default threshold
                            res = s
                            break
                    
                    if res:
                        # 1. Sentiment Alignment Guard (QUANT FIX: pass current_time)
                        # In backtest mode, sim_time ensures only historical data is used
                        # for DXY bias calculation - no future look-ahead possible.
                        if not sentiment_manager.is_aligned(symbol, res['signal'], sim_time=current_time):
                            continue
                            
                        # 2. Exhaustion Wick Guard
                        if PriceAction.is_exhaustion_candle(df_m5.iloc[idx-1], res['signal']):
                            continue
                            
                        # 3. SFP Rejection Guard (Liquidity Sweep)
                        # QUANT FIX: Use [:idx] not [:idx+1] so the current bar being
                        # evaluated is never included (it hasn't closed yet at entry time).
                        if PriceAction.is_liquidity_sweep_rejection(df_m5.iloc[:idx], res['signal']):
                            continue

                        entry_price = df_m5.iloc[idx]['open']
                        
                        # RR Filter
                        risk = abs(entry_price - res['sl'])
                        reward = abs(res['tp'] - entry_price)
                        rr = reward / risk if risk > 0 else 0
                        
                        if rr < getattr(config, 'MINIMUM_RR_THRESHOLD', 1.0):
                            continue

                        pip_size = config.SYMBOL_PIP_SIZE.get(symbol, 0.0001)
                        sl_pips = abs(entry_price - res['sl']) / pip_size
                        
                        # Safety: Minimum 5 pip SL to prevent lot size blowup
                        sl_pips = max(5.0, sl_pips)
                        # Coast Mode
                        current_pnl_pct = (self.balance / self.initial_balance - 1) * 100
                        risk_decimal = config.RISK_PERCENT / 100.0
                        if current_pnl_pct >= getattr(config, 'COAST_MODE_THRESHOLD', 7.0):
                            risk_decimal = getattr(config, 'COAST_MODE_RISK', 0.1) / 100.0
                        
                        risk_amount = self.balance * risk_decimal
                        sym_info = mt5.symbol_info(symbol)
                        contract_size = sym_info.trade_contract_size if sym_info else (100 if 'XAU' in symbol else 100000)
                        
                        # Use the possibly adjusted SL for lot calculation
                        adjusted_sl_dist = sl_pips * pip_size
                        lot_size = risk_amount / (adjusted_sl_dist * contract_size)
                        
                        # Round and clamp to match RiskManager
                        if sym_info:
                            step = sym_info.volume_step
                            lot_size = round(lot_size / step) * step
                            lot_size = max(sym_info.volume_min, min(sym_info.volume_max, lot_size))
                        else:
                            lot_size = round(lot_size, 2)
                        
                        if lot_size <= 0: continue
                        
                        # Compute ATR at entry time for use in slippage model at close
                        atr_pips = 10.0  # safe fallback
                        try:
                            atr_price = PriceAction.calculate_atr(m5_slice, period=14)
                            if atr_price and atr_price > 0:
                                atr_pips = atr_price / pip_size
                        except Exception:
                            pass

                        active_trades.append({
                            'symbol': symbol, 'type': res['signal'], 'entry_price': entry_price,
                            'sl': res['sl'], 'tp': res['tp'], 'entry_time': current_time, 'pip_size': pip_size,
                            'initial_sl_pips': sl_pips, 'atr_pips': atr_pips,
                            'lot_size': lot_size, 'contract_size': contract_size,
                            'strategy': res.get('strategy', 'Unknown')
                        })
                        daily_trade_count += 1

            self.total_equity.append(self.balance)

        self._report()
        self._export_results()
        self.send_telegram_report()

    def _export_results(self):
        """Export backtest data to JSON for external visualization/AI analysis."""
        os.makedirs("backtesting", exist_ok=True)
        
        # Calculate Drawdowns
        equity_series = pd.Series(self.total_equity)
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max * 100
        
        results = {
            "summary": {
                "initial_balance": self.initial_balance,
                "final_balance": self.balance,
                "total_profit": self.balance - self.initial_balance,
                "total_profit_pct": (self.balance / self.initial_balance - 1) * 100,
                "total_trades": len(self.trades),
                "win_rate": (len([t for t in self.trades if t['pnl'] > 0]) / len(self.trades) * 100) if self.trades else 0,
                "max_drawdown": float(drawdown.min()),
                "profit_factor": sum([t['pnl'] for t in self.trades if t['pnl'] > 0]) / abs(sum([t['pnl'] for t in self.trades if t['pnl'] < 0])) if any(t['pnl'] < 0 for t in self.trades) else 1.0
            },
            "strategy_pnl": self.strategy_pnl,
            "equity_curve": self.total_equity,
            "trades": [
                {
                    "symbol": t['symbol'],
                    "pnl": t['pnl'],
                    "time": t['time'].isoformat(),
                    "strategy": t['strategy']
                } for t in self.trades
            ]
        }
        
        with open("backtesting/results.json", "w") as f:
            json.dump(results, f, indent=4)
        print("Backtest results exported to backtesting/results.json")

    def _close_trade(self, trade, exit_price, exit_time):
        if trade['type'] == 'BUY':
            trade_pnl = (exit_price - trade['entry_price']) * trade['contract_size'] * trade['lot_size']
        else:
            trade_pnl = (trade['entry_price'] - exit_price) * trade['contract_size'] * trade['lot_size']

        # --- QUANT FIX: ATR-Based Volatility Slippage Model ---
        # BEFORE: random.uniform(0, 1.0) pips - completely unscientific.
        # NOW: Slippage is proportional to ATR at the time of the trade,
        # reflecting real liquidity conditions. During news / high vol, ATR
        # spikes → slippage spikes. During calm sessions, slippage is minimal.
        #
        # Formula: slippage_cost = ATR_at_trade_time * slippage_factor
        #   slippage_factor = 0.5% of ATR (normal) up to 2.0% (high vol proxy)
        #
        # ATR is computed from the M5 slice that was used for entry.
        symbol = trade['symbol']
        pip_size = trade['pip_size']
        atr_value = trade.get('atr_pips', 10.0)  # fallback: 10 pips

        # Scale slippage between 0.5% and 2% of ATR in price terms
        # (Higher initial_sl_pips implies more volatile conditions)
        sl_atr_ratio = trade.get('initial_sl_pips', 10.0) / max(atr_value, 1.0)
        slippage_factor = min(0.005 + (sl_atr_ratio * 0.002), 0.02)  # clamp 0.5–2%
        slippage_cost = (atr_value * pip_size * slippage_factor) * trade['contract_size'] * trade['lot_size']

        # Fixed commission: $3 per lot per side (industry standard round-trip = $6/lot)
        commission = 6.0 * trade['lot_size']

        # Spread penalty: 1 pip for major pairs, 2 pips for Gold/exotic
        base_spread_pips = 2.0 if 'XAU' in symbol or 'JPY' in symbol else 1.0
        spread_penalty = (base_spread_pips * pip_size) * trade['contract_size'] * trade['lot_size']

        trade_pnl = trade_pnl - commission - spread_penalty - slippage_cost

        strat = trade['strategy']
        self.strategy_pnl[strat] = self.strategy_pnl.get(strat, 0) + trade_pnl
        self.balance += trade_pnl
        self.trades.append({'symbol': trade['symbol'], 'pnl': trade_pnl, 'time': exit_time, 'strategy': strat})

    def _report(self):
        print(f"\n{'='*55}")
        print(f"  CHALLENGE RESULT: ${self.balance:.2f}  ({(self.balance/self.initial_balance - 1):.2%})")
        print(f"{'='*55}")
        print(f"  Initial Balance : ${self.initial_balance:.2f}")
        print(f"  Total Trades    : {len(self.trades)}")

        if not self.trades:
            print("  No trades executed.")
            return

        # --- FIX 3: Full Institutional Quant Metrics ---
        returns = pd.Series([t['pnl'] for t in self.trades])
        win_trades  = returns[returns > 0]
        loss_trades = returns[returns < 0]

        win_rate    = len(win_trades) / len(returns) * 100 if len(returns) > 0 else 0
        avg_win     = win_trades.mean()  if len(win_trades)  > 0 else 0
        avg_loss    = loss_trades.mean() if len(loss_trades) > 0 else 0
        expectancy  = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)
        profit_factor = (win_trades.sum() / abs(loss_trades.sum())
                         if len(loss_trades) > 0 and loss_trades.sum() != 0 else float('inf'))
        wl_ratio    = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        # Sharpe: annualised using trade-level returns (not daily — we have too few trades for daily)
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 1 and returns.std() > 0 else 0

        # Calmar: annualised return / max drawdown
        equity_series = pd.Series(self.total_equity)
        rolling_max   = equity_series.cummax()
        drawdown_pct  = ((equity_series - rolling_max) / rolling_max * 100)
        max_dd        = abs(drawdown_pct.min())
        annual_return = (self.balance / self.initial_balance - 1) * (12 / max(self.months, 1)) * 100
        calmar        = (annual_return / max_dd) if max_dd > 0 else float('inf')

        # Max consecutive losses
        max_consec_loss = 0
        consec = 0
        for pnl in returns:
            if pnl < 0:
                consec += 1
                max_consec_loss = max(max_consec_loss, consec)
            else:
                consec = 0

        print(f"\n  --- Performance Metrics ---")
        print(f"  Win Rate          : {win_rate:.1f}%")
        print(f"  Profit Factor     : {profit_factor:.2f}    (need >1.5)")
        print(f"  Expectancy/trade  : ${expectancy:.2f}  (need >$0)")
        print(f"  Avg Win           : ${avg_win:.2f}")
        print(f"  Avg Loss          : ${avg_loss:.2f}")
        print(f"  Win/Loss Ratio    : {wl_ratio:.2f}x")
        print(f"  Sharpe Ratio      : {sharpe:.2f}    (need >1.5)")
        print(f"  Calmar Ratio      : {calmar:.2f}    (need >1.0)")
        print(f"  Max Drawdown      : {max_dd:.2f}%")
        print(f"  Max Consec Losses : {max_consec_loss}")
        print(f"  Sample Size       : {len(returns)} trades  {'(!) LOW - need 300+' if len(returns) < 50 else '(OK)'}")

        print(f"\n  --- Strategy Ranking ---")
        for strat, pnl in sorted(self.strategy_pnl.items(), key=lambda x: x[1], reverse=True):
            print(f"  • {strat:30}: ${pnl:10.2f}")
        print(f"{'='*55}\n")

            
        plt.figure(figsize=(10, 6))
        plt.plot(self.total_equity, color='purple')
        plt.title("Backtest with Daily Target/Loss Limits")
        os.makedirs("backtesting", exist_ok=True)
        plt.savefig("backtesting/challenge_audit.png")

    def send_telegram_report(self):
        if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
            print("Telegram credentials missing, skipping report.")
            return

        token = config.TELEGRAM_BOT_TOKEN
        chat_id = config.TELEGRAM_CHAT_ID
        
        profit = self.balance - self.initial_balance
        profit_pct = (self.balance / self.initial_balance - 1) * 100
        win_trades = [t for t in self.trades if t['pnl'] > 0]
        win_rate = (len(win_trades) / len(self.trades) * 100) if self.trades else 0

        strat_lines = []
        for strat, pnl in sorted(self.strategy_pnl.items(), key=lambda x: x[1], reverse=True):
            strat_lines.append(f"• {strat}: <b>${pnl:.2f}</b>")
        strat_summary = "\n".join(strat_lines)

        report_text = (
            f"📊 <b>Backtest Results (Last {self.months} Months)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Final Balance:</b> ${self.balance:.2f}\n"
            f"📈 <b>Total Profit:</b> ${profit:.2f} ({profit_pct:.2f}%)\n"
            f"🎯 <b>Win Rate:</b> {win_rate:.1f}%\n"
            f"📝 <b>Total Trades:</b> {len(self.trades)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>Strategy Ranking:</b>\n{strat_summary}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Guardian Limits Used:</b>\n"
            f"   • Target: {self.profit_target_pct}%\n"
            f"   • Limit: {self.loss_limit_pct}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <i>Optimized for FundedNext $5k Challenge</i>"
        )

        # Send text
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": report_text, "parse_mode": "HTML"})

        # Send image
        img_path = "backtesting/challenge_audit.png"
        if os.path.exists(img_path):
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(img_path, "rb") as photo:
                requests.post(url, data={"chat_id": chat_id}, files={"photo": photo})

if __name__ == "__main__":
    import sys
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    mbt = MultiBacktester(initial_balance=5000.0)
    if mbt.fetch_all_data(months=months): mbt.run_combined()
    mt5.shutdown()

