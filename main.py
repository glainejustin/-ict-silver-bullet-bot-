# -*- coding: utf-8 -*-
import sys
import os
import math
# Ensure the root directory is in the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
import time
import logging
from datetime import datetime, timedelta
import json

# Core Modules
from core.connection import MT5Connection
from core.data_fetcher import DataFetcher
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from core.signal_aggregator import SignalAggregator
from core.trade_manager import TradeManager
from core.alert_manager import AlertManager
from core.news_manager import NewsManager
from core.performance_tracker import PerformanceTracker
from core.sentiment_manager import SentimentManager
from core.symbol_cache import SymbolInfoCache
from core.time_utils import get_mt5_time_utc

# Strategies
from strategies.raja_banks import RajaBanksStrategy
from strategies.london_breakout import LondonBreakoutStrategy
from strategies.silver_bullet import SilverBulletStrategy
from strategies.pure_price_action import PurePriceActionStrategy
import pytz

# Configuration
import config
from backtest_combined import MultiBacktester

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_activity.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MainBot")

def get_current_trade_load(magic_number, day_start_time):
    """
    Returns (active_pendings + filled_deals_today).
    This ensures non-activated limits don't count towards the quota once they expire.
    """
    # 1. Count Active Pending Orders
    orders = mt5.orders_get(magic=magic_number)
    pending_count = len(orders) if orders else 0
    
    from core.time_utils import get_broker_offset, get_mt5_time_utc
    
    # 2. Get today's start logic
    now = get_mt5_time_utc()
    broker_offset = get_broker_offset()
    broker_midnight = datetime.combine(day_start_time, datetime.min.time())
    start_of_day_utc = (broker_midnight - timedelta(hours=broker_offset)).replace(tzinfo=pytz.UTC)
    
    deals = mt5.history_deals_get(start_of_day_utc, now)
    filled_count = 0
    if deals:
        for d in deals:
            # entry=0 means in, entry=1 means out. Filter by magic number.
            if d.entry == 0 and d.magic == magic_number:
                filled_count += 1
                
    return pending_count + filled_count

def check_account_limits(order_manager, day_start_equity, challenge_start_balance, trading_days):
    """
    Funded Guardian:    Returns: 'STOP_PERMANENT', 'STOP_DAILY', or 'CONTINUE'
    """
    account = mt5.account_info()
    if not account: 
        logger.warning("Account info unavailable. Guardian continuing in safety mode.")
        return 'CONTINUE'
    
    current_equity = account.equity
    daily_profit_pct = ((current_equity - day_start_equity) / day_start_equity) * 100
    total_profit_pct = ((current_equity - challenge_start_balance) / challenge_start_balance) * 100
    
    # 1. Overall Profit Target (8%)
    if total_profit_pct >= config.OVERALL_PROFIT_TARGET_PERCENT:
        if len(trading_days) >= config.MIN_TRADING_DAYS:
            logger.info(f"CHALLENGE PASSED! Total Profit: {total_profit_pct:.2f}%. Min days met. Halting bot.")
            close_all_trades(order_manager, config.MAGIC_NUMBER)
            return 'STOP_PERMANENT'
        else:
            logger.info(f"GOAL REACHED! Profit: {total_profit_pct:.2f}%. Waiting for min trading days ({len(trading_days)}/{config.MIN_TRADING_DAYS}).")
            return 'STOP_DAILY'

    # 2. Daily Profit Target
    if daily_profit_pct >= config.DAILY_PROFIT_TARGET_PERCENT:
        logger.info(f"DAILY GOAL! Profit: {daily_profit_pct:.2f}%. Pausing for the day.")
        close_all_trades(order_manager, config.MAGIC_NUMBER)
        return 'STOP_DAILY'
        
    # 3. Daily Loss Limit
    if daily_profit_pct <= -config.MAX_DAILY_LOSS_PERCENT:
        logger.error(f"DAILY LIMIT! Loss: {daily_profit_pct:.2f}%. Pausing for the day.")
        close_all_trades(order_manager, config.MAGIC_NUMBER)
        return 'STOP_DAILY'

    # 4. Maximum Total Loss
    if total_profit_pct <= -config.MAX_TOTAL_LOSS_PERCENT:
        logger.error(f"MAX LOSS LIMIT! Total Loss: {total_profit_pct:.2f}%. Permanent halt.")
        close_all_trades(order_manager, config.MAGIC_NUMBER)
        return 'STOP_PERMANENT'
        
    return 'CONTINUE'

def close_all_trades(order_manager, magic_number=None):
    """Closes all open positions and deletes pending orders immediately, optionally filtered by magic number."""
    positions = mt5.positions_get()
    if positions:
        for pos in positions:
            if magic_number and pos.magic != magic_number: continue
            order_manager.close_position(pos)
            logger.info(f"Closed {pos.symbol} ticket {pos.ticket}")
    
    orders = mt5.orders_get()
    if orders:
        for order in orders:
            if magic_number and order.magic != magic_number: continue
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
            }
            mt5.order_send(request)
            logger.info(f"Deleted pending {order.symbol} ticket {order.ticket}")

def main():
    logger.info("=" * 60)
    logger.info("  FUNDEDNEXT SIGNAL ASSISTANT")
    mode_str = "Auto (Bot executes trades automatically)" if config.AUTO_EXECUTE else "Semi-Manual (Trader confirms every trade)"
    logger.info(f"  Mode: {mode_str}")
    logger.info("=" * 60)
    
    mt5_conn = MT5Connection()
    if not mt5_conn.connect():
        return

    # Store bot start date for performance tracking
    bot_start_date = get_mt5_time_utc()
    bot_paused = False
    daily_limit_reached = False
    daily_trade_count = 0
    last_reset_day = bot_start_date.date()

    # Initialize Balances & Persistence
    acc_info = mt5.account_info()
    if acc_info is None:
        logger.error("CRITICAL: Failed to retrieve account info during startup. Ensure MT5 is running and logged in.")
        return
        
    day_start_equity = acc_info.equity # Default if no state
    
    state_file = "bot_state.json"
    initial_risks_stored = {}
    current_acc_id = acc_info.login
    
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            state = json.load(f)
            stored_acc_id = state.get("account_id")
            stored_balance = state.get("challenge_start_balance", acc_info.balance)
            
            # Reset if account ID changed OR if balance is wildly different (migration/error safety)
            balance_diff_pct = abs(stored_balance - acc_info.balance) / acc_info.balance if acc_info.balance > 0 else 0
            if stored_acc_id != current_acc_id or balance_diff_pct > 0.20:
                logger.warning(f"Account change or balance discrepancy detected! Resetting challenge metrics.")
                challenge_start_balance = acc_info.balance
                challenge_start_date = bot_start_date
                initial_risks_stored = {}
                daily_trade_count = 0
                last_day_pnl = 0.0
                partial_done = set()
                breakeven_done = set()
                trading_days = set()
                disabled_strats = []
                high_water_mark = acc_info.equity
                week_start_equity = acc_info.equity
                cooling_until = None
            else:
                challenge_start_balance = state.get("challenge_start_balance", acc_info.balance)
                challenge_start_date = datetime.fromisoformat(state.get("challenge_start_date", bot_start_date.isoformat()))
                initial_risks_stored = {int(k): v for k, v in state.get("initial_risks", {}).items()}
                daily_trade_count = state.get("daily_trade_count", 0)
                last_reset_day = datetime.fromisoformat(state.get("last_reset_day", bot_start_date.isoformat())).date()
                day_start_equity = state.get("day_start_equity", day_start_equity)
                last_day_pnl = state.get("last_day_pnl", 0.0)
                partial_done = set(state.get("partial_done", []))
                breakeven_done = set(state.get("breakeven_done", []))
                trading_days = set(state.get("trading_days", []))
                disabled_strats = state.get("disabled_strategies", [])
                high_water_mark = state.get("high_water_mark", acc_info.equity)
                week_start_equity = state.get("week_start_equity", acc_info.equity)
                cooling_until = state.get("cooling_until", None)
                # Override config with saved limits if they exist
                config.DAILY_PROFIT_TARGET_PERCENT = state.get("daily_profit_target", config.DAILY_PROFIT_TARGET_PERCENT)
                config.MAX_DAILY_LOSS_PERCENT = state.get("max_daily_loss", config.MAX_DAILY_LOSS_PERCENT)
                config.MAX_DAILY_TRADES = state.get("max_daily_trades", config.MAX_DAILY_TRADES)
    else:
        challenge_start_balance = acc_info.balance
        challenge_start_date = bot_start_date
        partial_done = set()
        breakeven_done = set()
        trading_days = set()
        disabled_strats = []
        last_day_pnl = 0.0
        week_start_equity = acc_info.equity
        high_water_mark = acc_info.equity
        cooling_until = None
    
    logger.info(f"Challenge Start Balance: ${challenge_start_balance:.2f}")
    logger.info(f"Day Starting Equity: ${day_start_equity:.2f}")

    # Track failed executions to prevent loops
    failed_executions = {} # {symbol: timestamp}
    
    # FIX 1: New-Candle Event Detection (replaces 15s sleep polling)
    # Store the last M5 candle timestamp seen per symbol.
    # Strategy scan only fires when a GENUINELY NEW 5-minute bar has formed.
    # This cuts worst-case entry latency from 15s to <500ms.
    last_candle_time = {symbol: 0 for symbol in config.SYMBOLS}  # epoch seconds

    data_fetcher = DataFetcher()
    risk_manager = RiskManager(account_balance=day_start_equity)
    risk_manager.challenge_start_balance = challenge_start_balance
    risk_manager.soft_recovery = (last_day_pnl < 0)
    if risk_manager.soft_recovery:
        logger.warning(f"Soft Recovery Mode Active! Previous day PnL: ${last_day_pnl:.2f}. Risk halved.")
    order_manager = OrderManager(magic_number=config.MAGIC_NUMBER)
    trade_manager = TradeManager(magic_number=config.MAGIC_NUMBER, initial_risks=initial_risks_stored, partial_done=partial_done, breakeven_done=breakeven_done)
    news_manager = NewsManager()
    sentiment_manager = SentimentManager()
    performance_tracker = PerformanceTracker(magic_number=config.MAGIC_NUMBER, challenge_start_date=challenge_start_date)

    # Alert Manager (Telegram + Console + Sound)
    alert_manager = AlertManager(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
        timeout=config.ALERT_TIMEOUT_SECONDS,
        sound_freq=config.ALERT_SOUND_FREQ,
        sound_duration=config.ALERT_SOUND_DURATION,
    )
    
    # Build strategies per symbol
    symbol_strategies = {}
    for symbol in config.SYMBOLS:
        strat_names = config.SYMBOL_STRATEGY_MAP.get(symbol, [])
        strats_for_symbol = []
        
        for s_name in strat_names:
            if s_name == "RajaBanksStrategy":
                strats_for_symbol.append(RajaBanksStrategy(f"Raja_{symbol}", symbol))
            elif s_name == "LondonBreakoutStrategy":
                strats_for_symbol.append(LondonBreakoutStrategy(f"London_{symbol}", symbol))
            elif s_name == "SilverBulletStrategy":
                strats_for_symbol.append(SilverBulletStrategy(f"Silver_{symbol}", symbol))
            elif s_name == "PurePriceActionStrategy":
                strats_for_symbol.append(PurePriceActionStrategy(f"PurePA_{symbol}", symbol))
            
        if strats_for_symbol:
            aggregator = SignalAggregator(strategies=strats_for_symbol, min_confidence_threshold=1.0)
            # Apply loaded disabled state
            for s_name in disabled_strats:
                aggregator.disable_strategy(s_name)
            symbol_strategies[symbol] = aggregator

    try:
        while True:
            # 1. Connection & Permission Check (PRE-FLIGHT)
            term_info = mt5.terminal_info()
            acc_info = mt5.account_info()

            # --- Check Telegram Commands (MOVE TO TOP FOR RESPONSIVENESS) ---
            # This ensures /status works even if the bot is "halted" by a limit
            commands = alert_manager.get_incoming_commands()
            for cmd in commands:
                if cmd == "/help" or cmd == "/start":
                    help_msg = (
                        "🤖 <b>Bot Commands</b>\n"
                        "━━━━━━━━━━━━━━\n"
                        "📊 /status  - Current account metrics\n"
                        "📈 /backtest X - Run X-month audit\n"
                        "🎯 /targetdays X - Est. time to X% profit\n"
                        "📜 /logs    - View recent 15 log lines\n"
                        "🔄 /resetchallenge - Reset benchmark to current balance\n"
                        "💰 /setprofit X - Set Daily Profit Target %\n"
                        "📉 /setloss X   - Set Max Daily Loss %\n"
                        "📦 /settrades X - Set Max Daily Trades\n"
                        "🚫 /disablestrategy Name - Turn off a strategy\n"
                        "✅ /enablestrategy Name - Turn on a strategy\n"
                        "⏸ /pause   - Pause new trades\n"
                        "▶️ /resume  - Resume trading\n"
                        "⏹ /stop    - Stop the bot\n"
                        "━━━━━━━━━━━━━━\n"
                        f"<i>Status: {'PAUSED' if bot_paused else 'RUNNING'}</i>"
                    )
                    alert_manager.send_message(help_msg)
                
                elif cmd.startswith("/backtest"):
                    try:
                        parts = cmd.split(" ")
                        months = int(parts[1]) if len(parts) > 1 else 3
                        alert_manager.send_message(f"📊 Starting {months}-month backtest audit... please wait.")
                        mbt = MultiBacktester(
                            initial_balance=challenge_start_balance, 
                            profit_target_pct=config.OVERALL_PROFIT_TARGET_PERCENT, 
                            loss_limit_pct=config.MAX_TOTAL_LOSS_PERCENT
                        )
                        if mbt.fetch_all_data(months=months):
                            mbt.run_combined()
                            alert_manager.send_message(f"✅ {months}-month backtest complete. Check results above.")
                        else:
                            alert_manager.send_message("❌ Backtest failed (MT5 data error).")
                    except:
                        alert_manager.send_message("❌ Error: Use format /backtest 1")

                elif cmd == "/status":
                    positions = mt5.positions_get(magic=config.MAGIC_NUMBER)
                    num_open = len(positions) if positions else 0
                    if acc_info:
                        metrics = performance_tracker.get_global_metrics()
                        status_msg = (
                            f"🤖 <b>Bot Status</b>\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"💰 Balance: ${acc_info.balance:.2f}\n"
                            f"📈 Equity:  ${acc_info.equity:.2f}\n"
                            f"🏁 Challenge Start: ${challenge_start_balance:.2f}\n"
                            f"📅 Trading Days: {len(trading_days)}/{config.MIN_TRADING_DAYS}\n"
                            f"📊 Total P/L: {((acc_info.equity/challenge_start_balance)-1)*100:.2f}% / {config.OVERALL_PROFIT_TARGET_PERCENT}%\n"
                            f"📊 Daily P/L: {((acc_info.equity/day_start_equity)-1)*100:.2f}% / {config.DAILY_PROFIT_TARGET_PERCENT}%\n"
                            f"🎯 Profit Factor: {metrics['profit_factor']:.2f}\n"
                            f"📉 Expectancy: ${metrics['expectancy']:.2f}\n"
                            f"🔄 Trade Load: {get_current_trade_load(config.MAGIC_NUMBER, last_reset_day)}/{config.MAX_DAILY_TRADES}\n"
                            f"📦 Open Pos: {num_open}\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"Scanning: {', '.join(config.SYMBOLS)}\n"
                            f"Status: {'⏸ PAUSED' if bot_paused or daily_limit_reached else '✅ RUNNING'}"
                        )
                        alert_manager.send_message(status_msg)
                
                elif cmd == "/logs":
                    log_file = "bot_activity.log"
                    if os.path.exists(log_file):
                        with open(log_file, "r") as f:
                            lines = f.readlines()
                            last_lines = "".join(lines[-15:])
                            alert_manager.send_message(f"📜 <b>Recent Logs:</b>\n<pre>{last_lines}</pre>")
                    else:
                        alert_manager.send_message("❌ Log file not found.")

                elif cmd == "/resume":
                    bot_paused = False
                    alert_manager.send_message("▶️ Trading resumed.")
                    logger.info("Bot resumed manually via Telegram.")

                elif cmd == "/stop":
                    alert_manager.send_message("🛑 Stopping bot as requested.")
                    logger.info("Bot stopped via Telegram command.")
                    return
                
                elif cmd.startswith("/setprofit"):
                    try:
                        new_target = float(cmd.split(" ")[1])
                        config.DAILY_PROFIT_TARGET_PERCENT = new_target
                        alert_manager.send_message(f"✅ Daily Profit Target updated to {new_target}%.")
                    except:
                        alert_manager.send_message("❌ Error: Use format /setprofit 5.0")

                elif cmd == "/pause":
                    bot_paused = True
                    alert_manager.send_message("⏸ Trading paused.")

            # -----------------------

            if term_info is None or acc_info is None or not term_info.connected:
                logger.warning("MT5 Connection lost or account info unavailable. Attempting reconnect...")
                mt5_conn.connect()
                time.sleep(5)
                continue

            if not mt5_conn.check_trade_permissions():
                logger.warning("Trading permissions unavailable. Skipping this cycle.")
                time.sleep(config.SLEEP_SECONDS)
                continue

            # 0. Friday Close Guard
            current_time_utc = get_mt5_time_utc()
            if current_time_utc.weekday() == 4 and current_time_utc.hour >= config.FRIDAY_CLOSE_HOUR:
                active_pos = mt5.positions_get(magic=config.MAGIC_NUMBER)
                if active_pos:
                    logger.info("Friday evening detected. Closing all positions for weekend safety.")
                    close_all_trades(order_manager, config.MAGIC_NUMBER)
                    alert_manager.send_message("🛡️ <b>Weekend Protection</b>\nFriday evening reached. All trades closed.")
                time.sleep(60) # Idle until market close
                continue

            # 2c. Daily Profit/Loss Guardian (Consolidated Loop Logic)
            current_equity = acc_info.equity
            daily_pnl_pct = ((current_equity - day_start_equity) / day_start_equity) * 100 if day_start_equity > 0 else 0
            
            # Check for Daily Goal or Max Loss
            if daily_pnl_pct >= getattr(config, 'DAILY_GOAL_PERCENT', getattr(config, 'DAILY_PROFIT_TARGET_PERCENT', 5.0)) or daily_pnl_pct <= -config.MAX_DAILY_LOSS_PERCENT:
                if not daily_limit_reached:
                    logger.info(f"FUNDED GUARDIAN: Daily Target/Loss Hit ({daily_pnl_pct:.2f}%). Halting until tomorrow.")
                    close_all_trades(order_manager, config.MAGIC_NUMBER)
                    alert_manager.send_message(f"🎯 <b>Daily Goal/Limit Reached</b>\nProfit/Loss: {daily_pnl_pct:.2f}%\nBot halting until tomorrow to protect account.")
                    daily_limit_reached = True
                time.sleep(10)
                continue
            
            # 2d. Advanced Drawdown Protection (High-Water Mark)
            high_water_mark = max(high_water_mark, current_equity)
            trailing_drawdown = ((high_water_mark - current_equity) / high_water_mark) * 100 if high_water_mark > 0 else 0
            if trailing_drawdown >= config.MAX_TRAILING_DRAWDOWN_PERCENT:
                logger.error(f"🛑 TRAILING DRAWDOWN LIMIT! Peak: ${high_water_mark:.2f} | Current: ${current_equity:.2f} | DD: {trailing_drawdown:.2f}%")
                close_all_trades(order_manager, config.MAGIC_NUMBER)
                alert_manager.send_message(
                    f"🛑 <b>TRAILING DRAWDOWN LIMIT</b>\n"
                    f"Peak Equity: ${high_water_mark:.2f}\n"
                    f"Current Equity: ${current_equity:.2f}\n"
                    f"Drawdown: {trailing_drawdown:.2f}% (Limit: {config.MAX_TRAILING_DRAWDOWN_PERCENT}%)\n"
                    f"Bot halting permanently for account safety."
                )
                break # Permanent Halt
            else:
                # Reset daily limit reached if we are back within bounds (e.g., after a day reset)
                # Note: The day reset logic below handles resetting the flag.
                pass
            
            # 2e. Weekly Cooling Guard (Psychological Tilt Protection)
            if 'cooling_until' in locals() and cooling_until:
                if datetime.now(pytz.UTC) < datetime.fromisoformat(cooling_until):
                    logger.info(f"EQUITY COOLING ACTIVE until {cooling_until}. Standing down.")
                    time.sleep(60)
                    continue
                else:
                    cooling_until = None # Cooling period ended
            
            week_pnl_pct = ((current_equity - week_start_equity) / week_start_equity) * 100 if week_start_equity > 0 else 0
            if week_pnl_pct <= -config.WEEKLY_LOSS_LIMIT_PERCENT:
                cooling_until = (datetime.now(pytz.UTC) + timedelta(hours=24)).isoformat()
                logger.warning(f"WEEKLY LOSS LIMIT HIT ({week_pnl_pct:.2f}%). Entering 24h Cooling Period.")
                close_all_trades(order_manager, config.MAGIC_NUMBER)
                alert_manager.send_message(
                    f"🧠 <b>EQUITY COOLING ACTIVE</b>\n"
                    f"Weekly Loss: {week_pnl_pct:.2f}% (Limit: {config.WEEKLY_LOSS_LIMIT_PERCENT}%)\n"
                    f"Standing down for 24 hours to prevent tilt and re-evaluate."
                )
                continue
                
            # --- QUANT FIX: Broker Server Midnight Alignment ---
            # Use MT5 server time (via broker offset) for day boundaries.
            # Prop firm daily drawdown limits reset at BROKER midnight (GMT+2/+3),
            # NOT local system time. A mismatch here risks instant account disqualification.
            from core.time_utils import get_broker_offset
            broker_offset = get_broker_offset()
            broker_now = current_time_utc + timedelta(hours=broker_offset)
            if broker_now.date() != last_reset_day:
                # Weekly reset on Monday
                if current_time_utc.weekday() == 0:
                    week_start_equity = current_equity
                    logger.info(f"NEW WEEK DETECTED. Resetting week_start_equity to ${week_start_equity:.2f}")
                
                last_day_pnl = acc_info.equity - day_start_equity
                day_start_equity = acc_info.equity
                daily_trade_count = 0
                daily_limit_reached = False  # Reset for the new day
                # Send Daily Recap
                from datetime import time as dt_time
                yesterday_pnl = last_day_pnl
                yesterday_trades = mt5.history_deals_get(
                    datetime.combine(last_reset_day, dt_time.min).replace(tzinfo=pytz.UTC),
                    datetime.combine(last_reset_day, dt_time.max).replace(tzinfo=pytz.UTC)
                )
                deal_count = 0
                win_count = 0
                if yesterday_trades:
                    for d in yesterday_trades:
                        if d.magic == config.MAGIC_NUMBER and d.entry == 1: # Out deals
                            deal_count += 1
                            if d.profit > 0: win_count += 1
                
                win_rate = (win_count / deal_count * 100) if deal_count > 0 else 0
                risk_mode = "LOW (Soft Recovery)" if risk_manager.soft_recovery else "NORMAL"
                
                summary_msg = (
                    f"📅 <b>Daily Recap: {last_reset_day.strftime('%Y-%m-%d')}</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"💰 P/L: <b>${yesterday_pnl:+.2f}</b>\n"
                    f"📦 Trades: {deal_count}\n"
                    f"🎯 Win Rate: {win_rate:.1f}%\n"
                    f"🛡️ Risk Mode: {risk_mode}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"<i>Guardian resetting for a new day...</i>"
                )
                alert_manager.send_message(summary_msg)

                last_reset_day = broker_now.date()  # Track in broker server date
                day_start_equity = current_equity
                daily_trade_count = 0
                
                # Update Soft Recovery
                risk_manager.soft_recovery = (last_day_pnl < 0)
                if risk_manager.soft_recovery:
                    logger.warning(f"Soft Recovery Mode Active! Previous day PnL: ${last_day_pnl:.2f}. Risk halved.")
                else:
                    logger.info(f"New day detected. Previous day PnL: ${last_day_pnl:.2f}. Normal risk active.")

            # Save state periodically
            with open(state_file, "w") as f:
                ts = trade_manager.get_state()
                json.dump({
                    "account_id": current_acc_id,
                    "challenge_start_balance": challenge_start_balance,
                    "challenge_start_date": challenge_start_date.isoformat(),
                    "initial_risks": ts["initial_risks"],
                    "last_reset_day": last_reset_day.isoformat(),
                    "day_start_equity": day_start_equity,
                    "last_day_pnl": last_day_pnl,
                    "partial_done": list(partial_done),
                    "breakeven_done": list(breakeven_done),
                    "trading_days": list(trading_days),
                    "daily_profit_target": config.DAILY_PROFIT_TARGET_PERCENT,
                    "max_daily_loss": config.MAX_DAILY_LOSS_PERCENT,
                    "max_daily_trades": config.MAX_DAILY_TRADES,
                    "high_water_mark": high_water_mark,
                    "week_start_equity": week_start_equity,
                    "cooling_until": cooling_until,
                    "disabled_strategies": [s.name for agg in symbol_strategies.values() for s in agg.strategies if not s.enabled]
                }, f)

            # 2. Guardian Check (Advanced Metrics)
            guardian_status = check_account_limits(order_manager, day_start_equity, challenge_start_balance, trading_days)
            if guardian_status == 'STOP_PERMANENT':
                alert_manager.send_message("🛑 <b>PERMANENT HALT</b>\nGuardian has stopped the bot to protect the account or celebrate a challenge pass.")
                logger.info("Guardian has halted the bot for safety/success.")
                break
            elif guardian_status == 'STOP_DAILY':
                if not daily_limit_reached:
                    logger.info("Guardian check triggered STOP_DAILY. Halting new entries.")
                    daily_limit_reached = True
                time.sleep(10)
                continue
            else:
                # If we are here, we are good to continue
                pass

            # --- Scan for new signals ---
            # --- Cycle Start ---
            symbol_cache = SymbolInfoCache()
            
            current_trade_load = get_current_trade_load(config.MAGIC_NUMBER, last_reset_day)
            
            # FIX 1: Only run full strategy scan when at least ONE symbol has a new M5 candle.
            # Uses integer-division on tick.time to detect 5-minute boundary crossings.
            new_candle_ready = False
            for sym in config.SYMBOLS:
                tick = mt5.symbol_info_tick(sym)
                if tick:
                    bar_boundary = (tick.time // 300) * 300  # M5 = 300 seconds
                    if bar_boundary != last_candle_time.get(sym, 0):
                        last_candle_time[sym] = bar_boundary
                        new_candle_ready = True
            
            if current_trade_load >= config.MAX_DAILY_TRADES and not daily_limit_reached:
                logger.info(f"Daily trade limit ({config.MAX_DAILY_TRADES}) reached - halting new entries.")
                daily_limit_reached = True

            if not bot_paused and not daily_limit_reached and new_candle_ready:
                active_positions = mt5.positions_get(magic=config.MAGIC_NUMBER)
                pending_orders = mt5.orders_get(magic=config.MAGIC_NUMBER)
                
                open_symbols = set(pos.symbol for pos in active_positions) if active_positions else set()
                if pending_orders:
                    for o in pending_orders:
                        open_symbols.add(o.symbol)
                
                for symbol, aggregator in symbol_strategies.items():
                    # Track ticks for TPS calculation
                    current_tps = symbol_cache.get_tps(symbol) if hasattr(symbol_cache, 'get_tps') else 0.0
                    
                    # --- ZEN COOLDOWN CHECK ---
                    last_loss_time = failed_executions.get(symbol, 0)
                    if time.time() - last_loss_time < 300: # 5 Minute Zen Cooldown
                        logger.info(f"[{symbol}] ZEN COOLDOWN: Resting after recent loss. Skipping scan.")
                        continue
                    
                    # 1. Data Heartbeat (Stale Price Guard)
                    tick = symbol_cache.get_tick(symbol)
                    if tick:
                        from core.time_utils import get_broker_offset
                        tick_time_utc = tick.time - (get_broker_offset() * 3600) if hasattr(tick, 'time') else time.time()
                        lag = abs(time.time() - tick_time_utc)
                        if lag > config.DATA_STALE_THRESHOLD:
                            logger.warning(f"[{symbol}] HEARTBEAT FAIL | Data is stale ({lag:.1f}s). Skipping scan.")
                            continue
                    
                    # Correlation Check
                    is_correlated_blocked = False
                    for group in getattr(config, 'CORRELATION_GROUPS', []):
                        if symbol in group:
                            other_symbols = [s for s in group if s != symbol]
                            if any(s in open_symbols for s in other_symbols):
                                is_correlated_blocked = True
                                break
                    if is_correlated_blocked:
                        logger.info(f"[{symbol}] STATUS | Blocked by Correlation Filter")
                        continue
                    
                    if news_manager.is_news_window(symbol, current_time_utc, config.NEWS_NO_TRADE_MINUTES):
                        logger.info(f"[{symbol}] STATUS | News Buffer Active")
                        continue

                    data_ltf = data_fetcher.get_historical_data(symbol, mt5.TIMEFRAME_M5, 100)
                    data_htf = data_fetcher.get_historical_data(symbol, mt5.TIMEFRAME_H1, 100)
                    data_struct = data_fetcher.get_historical_data(symbol, mt5.TIMEFRAME_H4, 100)

                    if data_ltf is None or data_htf is None: continue

                    signal_res = aggregator.aggregate_signals(data_ltf, data_htf, data_struct, current_time_utc)
                    logger.info(f"[{symbol}] STATUS | {signal_res.get('reason', 'Scanning...')}")

                    if signal_res['signal'] != 'HOLD':
                        # --- EXECUTION LOGIC ---
                        strategy_used = signal_res.get('strategy', 'Unknown')
                        # Use .get() without default so None triggers execute_trade's fallback to tick.ask/bid
                        entry_price = signal_res.get('entry_price')
                        
                        # Check strategy performance (Expectancy-Based)
                        strat_perf = performance_tracker.get_strategy_metrics(strategy_used)
                        if strat_perf['count'] >= 10 and strat_perf['expectancy'] < 0:
                            logger.info(f"[{symbol}] Skipping {strategy_used} - Negative Expectancy (${strat_perf['expectancy']:.2f}). Auto-Disabled.")
                            continue

                        # Spread Guard
                        tick = symbol_cache.get_tick(symbol)
                        if tick:
                            pip_size = config.SYMBOL_PIP_SIZE.get(symbol, 0.0001)
                            current_spread = (tick.ask - tick.bid) / pip_size
                            max_spread = config.MAX_SPREAD_PIPS.get(symbol, 999)
                            if current_spread > max_spread:
                                logger.info(f"[{symbol}] Entry blocked: Spread {current_spread:.1f} > Max {max_spread}")
                                continue
                            
                            # Liquidity Guard (Institutional Cost vs Move)
                            from core.price_action import PriceAction
                            atr_val = PriceAction.calculate_atr(data_ltf, period=14)
                            if atr_val > 0:
                                liquidity_cost = (tick.ask - tick.bid) / (atr_val * pip_size) if pip_size > 0 else 0
                                if liquidity_cost > 0.15: # 15% cost threshold
                                    logger.info(f"[{symbol}] Entry blocked: High Liquidity Cost ({liquidity_cost:.2%} of ATR)")
                                    continue

                        # Sentiment Guard (Institutional Wind)
                        if not sentiment_manager.is_aligned(symbol, signal_res['signal']):
                            logger.info(f"[{symbol}] Signal {signal_res['signal']} blocked by Macro Sentiment (DXY Conflict)")
                            continue

                        # H4 Bias Filter (Trend Alignment)
                        h4_data = symbol_cache.get_rates(symbol, mt5.TIMEFRAME_H4, 2)
                        if h4_data is not None and len(h4_data) >= 2:
                            last_h4 = h4_data.iloc[-1]
                            h4_bias = "BULLISH" if last_h4['close'] > last_h4['open'] else "BEARISH"
                            if (signal_res['signal'] == 'BUY' and h4_bias != "BULLISH") or \
                               (signal_res['signal'] == 'SELL' and h4_bias != "BEARISH"):
                                logger.info(f"[{symbol}] Signal {signal_res['signal']} filtered by H4 Bias ({h4_bias})")
                                continue
                        
                        # Exhaustion Wick Guard (Institutional Rejection)
                        if PriceAction.is_exhaustion_candle(data_ltf.iloc[-1], signal_res['signal']):
                            logger.info(f"[{symbol}] Signal {signal_res['signal']} blocked: Exhaustion Wick detected (Fading Momentum).")
                            continue

                        # RR Filter Check
                        risk_pips = abs(entry_price - signal_res['sl'])
                        reward_pips = abs(signal_res['tp'] - entry_price)
                        rr = reward_pips / risk_pips if risk_pips > 0 else 0
                        
                        if rr < getattr(config, 'MINIMUM_RR_THRESHOLD', 1.0):
                            logger.info(f"[{symbol}] Skipping trade - Poor RR: {rr:.2f} (Min: {config.MINIMUM_RR_THRESHOLD})")
                            continue

                        # Calculate lot size with House Money protection
                        risk_manager.day_start_equity = day_start_equity
                        lot_size = risk_manager.calculate_lot_size(
                            symbol, signal_res['sl'], signal_res['signal'], 
                            entry_price=entry_price,
                            symbol_cache=symbol_cache, alert_manager=alert_manager
                        )
                        
                        if lot_size <= 0:
                            logger.info(f"[{symbol}] Skipping trade due to lot size constraint.")
                            continue
                        
                        if config.AUTO_EXECUTE:
                            alert_manager.send_message(
                                f"🚀 <b>Auto-Executing Trade</b>\n"
                                f"━━━━━━━━━━━━━━\n"
                                f"Symbol: {symbol}\n"
                                f"Strategy: {strategy_used}\n"
                                f"Action: {signal_res['signal']}\n"
                                f"Entry: {entry_price:.5f}\n"
                                f"SL: {signal_res['sl']:.5f}\n"
                                f"TP: {signal_res['tp']:.5f}\n"
                                f"Lot: {lot_size}"
                            )
                            approved = True
                        else:
                            approved = alert_manager.alert_and_confirm(signal_res, lot_size, symbol)

                        if approved:
                            last_fail = failed_executions.get(symbol, 0)
                            if time.time() - last_fail < 300: # 5 minute cooldown
                                logger.info(f"[{symbol}] Skipping signal due to recent execution failure cooldown.")
                                continue

                            # --- SFP REJECTION GUARD (Liquidity Sweep) ---
                            # Block if we just swept a significant high/low and rejected
                            if PriceAction.is_liquidity_sweep_rejection(symbol_cache.get_data(symbol, mt5.TIMEFRAME_M5), signal_res['signal']):
                                logger.info(f"[{symbol}] SFP GUARD: Liquidity sweep detected in opposite direction. Signal rejected.")
                                continue

                            trade_res = order_manager.execute_trade(
                                symbol=symbol, order_type=signal_res['signal'],
                                lot=lot_size, price=entry_price, sl=signal_res['sl'], tp=signal_res['tp'],
                                strategy_name=strategy_used, symbol_cache=symbol_cache
                            )
                            # 3. Execution Verification
                            if trade_res and hasattr(trade_res, 'retcode') and trade_res.retcode == mt5.TRADE_RETCODE_DONE:
                                logger.info(f"[{symbol}] TRADE EXECUTED | Order: {trade_res.order} | Price: {trade_res.price}")
                                order_manager.add_trade(trade_res.order, signal_res['sl'], signal_res['tp'], strategy_used)
                                daily_trade_count += 1
                                trading_days.add(current_time_utc.strftime("%Y-%m-%d"))
                                if symbol in failed_executions: del failed_executions[symbol]
                                alert_manager.send_message(
                                    f"✅ <b>TRADE PLACED</b>\n"
                                    f"Pair: {symbol}\n"
                                    f"Strategy: {strategy_used}\n"
                                    f"Action: {signal_res['signal']}\n"
                                    f"Price: {signal_res.get('entry_price', 0):.5f}"
                                )
                            else:
                                logger.error(f"[{symbol}] Execution failed. Entering 5m cooldown.")
                                failed_executions[symbol] = time.time()
                                alert_manager.send_message(f"❌ Execution failed for {symbol}. Cooling down for 5 mins.")
                        else:
                            logger.info(f"[{symbol}] Signal skipped by trader.")

            # --- Always manage open positions ---
            if config.AUTO_MANAGE_POSITIONS:
                for symbol in config.SYMBOLS:
                    trade_manager.manage_open_positions(symbol, symbol_cache=symbol_cache)

            time.sleep(0.5)  # FIX 1: 500ms heartbeat (candle detection throttles strategy scans)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
