# -*- coding: utf-8 -*-
import MetaTrader5 as mt5
import logging

logger = logging.getLogger("MT5Connection")

class MT5Connection:
    """
    Handles the initialization and connection to the MetaTrader 5 terminal.
    Includes comprehensive permission checks to catch AutoTrading issues early.
    """
    def connect(self):
        if not mt5.initialize():
            logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False

        # Layer 0: Ensure symbols are in Market Watch
        import config
        for symbol in config.SYMBOLS:
            if not mt5.symbol_select(symbol, True):
                logger.warning(f"Failed to select {symbol} in Market Watch. It may not be available.")

        # Layer 1: Server connectivity
        term_info = mt5.terminal_info()
        if term_info is None or not term_info.connected:
            logger.error("MT5 Terminal is not connected to the server. Please log in manually.")
            mt5.shutdown()
            return False

        # Layer 2: Terminal-wide Algo Trading button
        if not term_info.trade_allowed:
            logger.error(
                "ALGO TRADING IS DISABLED IN THE TERMINAL. "
                "Click the 'Algo Trading' button in the MT5 toolbar until it turns GREEN."
            )
            mt5.shutdown()
            return False

        # Layer 3: Account-level EA permission
        acc_info = mt5.account_info()
        if acc_info is None:
            logger.error("Failed to retrieve account info. Cannot verify trading permissions.")
            mt5.shutdown()
            return False

        if not acc_info.trade_expert:
            logger.warning(
                "Note: EA trading is technically disabled on this account, "
                "but the bot will proceed in Stealth Mode (Manual Emulation)."
            )

        if not acc_info.trade_allowed:
            logger.error(
                "TRADING IS DISABLED FOR THIS ACCOUNT. "
                "Check account status with your broker. "
                f"Account: {acc_info.name} | Broker: {acc_info.company}"
            )
            mt5.shutdown()
            return False

        logger.info(
            f"Connected to MetaTrader 5 | "
            f"Account: {acc_info.name} | "
            f"Broker: {acc_info.company} | "
            f"Balance: ${acc_info.balance:.2f}"
        )
        return True

    def check_trade_permissions(self) -> bool:
        """
        Re-checks live trading permissions mid-session.
        Returns True if all permissions are currently active.
        """
        term_info = mt5.terminal_info()
        acc_info = mt5.account_info()
        if term_info is None or acc_info is None:
            logger.warning("Could not verify trading permissions — MT5 may have disconnected.")
            return False
        if not term_info.trade_allowed:
            logger.warning("Algo Trading button is OFF. Bot is paused until it is re-enabled.")
            return False
        return True

    def disconnect(self):
        mt5.shutdown()
        logger.info("MT5 connection closed.")
