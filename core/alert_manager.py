# -*- coding: utf-8 -*-
import logging
import time
import threading
import winsound
import requests
import os
from datetime import datetime

logger = logging.getLogger("AlertManager")


class AlertManager:
    """
    Handles signal alerts via Telegram (with inline Execute/Skip buttons)
    and console display. Compliant with Funded Elite EA policy — the trader
    makes every execution decision.
    """

    def __init__(self, bot_token: str = None, chat_id: str = None,
                 timeout: int = 60, sound_freq: int = 1000, sound_duration: int = 500):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.sound_freq = sound_freq
        self.sound_duration = sound_duration
        self.telegram_enabled = bool(bot_token and chat_id)
        self._last_update_id = 0
        self._update_buffer = []

        if self.telegram_enabled:
            logger.info("Telegram alerts enabled.")
            # Clear any stale updates so we don't process old button presses
            self._flush_old_updates()
        else:
            logger.warning("Telegram not configured. Using console-only mode.")

    def alert_and_confirm(self, signal: dict, lot_size: float, symbol: str) -> bool:
        alert_text = self._format_alert(signal, lot_size, symbol)
        self._print_console_alert(alert_text)
        threading.Thread(target=self._play_sound, daemon=True).start()
        if self.telegram_enabled:
            approved = self._telegram_confirm(alert_text, signal, symbol)
        else:
            approved = self._console_confirm()
        action = "ACCEPTED" if approved else "REJECTED"
        logger.info(f"[{symbol}] Signal {action} by trader - {signal['signal']} @ {signal.get('reason', '')}")
        return approved

    def _get_updates(self, timeout=1):
        """Fetch and buffer Telegram updates."""
        if not self.telegram_enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        try:
            params = {"offset": self._last_update_id + 1, "timeout": timeout}
            resp = requests.get(url, params=params, timeout=timeout+5)
            data = resp.json()
            if not data.get("ok"):
                return
            updates = data.get("result", [])
            if updates:
                self._update_buffer.extend(updates)
                self._last_update_id = updates[-1]["update_id"]
        except Exception as e:
            logger.debug(f"Update poll error: {e}")

    def get_incoming_commands(self) -> list:
        """Process buffered text commands."""
        self._get_updates(timeout=1)
        commands = []
        remaining = []
        for update in self._update_buffer:
            msg = update.get("message")
            if msg:
                sender_id = str(msg.get("from", {}).get("id", ""))
                if sender_id == str(self.chat_id) and msg.get("text"):
                    text = msg["text"].strip()
                    if text.startswith("/"):
                        commands.append(text.lower())
                        continue # Command consumed
            remaining.append(update)
        self._update_buffer = remaining
        return commands

    def send_message(self, text: str):
        self._send_telegram(text)

    def _poll_telegram_callback(self, callback_id: str, msg_id: int) -> bool:
        """Poll buffer for a specific inline button callback."""
        deadline = time.time() + self.timeout
        result_choice = False
        matched = False
        
        while time.time() < deadline:
            self._get_updates(timeout=5)
            remaining = []
            for update in self._update_buffer:
                cb = update.get("callback_query")
                if cb:
                    cb_data = cb.get("data", "")
                    if cb_data.endswith(callback_id):
                        sender_id = str(cb.get("from", {}).get("id", ""))
                        if sender_id == str(self.chat_id):
                            self._answer_callback(cb["id"])
                            if cb_data == f"exec_{callback_id}":
                                self._edit_message(msg_id, "✅ TRADE EXECUTED by trader.")
                                result_choice = True
                                matched = True
                            elif cb_data == f"skip_{callback_id}":
                                self._edit_message(msg_id, "❌ Signal skipped by trader.")
                                result_choice = False
                                matched = True
                            continue # Callback consumed
                remaining.append(update)
            self._update_buffer = remaining
            
            if matched: break
            time.sleep(0.5)

        if matched: return result_choice
        self._edit_message(msg_id, "⏰ Signal expired (no response). Skipped.")
        return False

    def _format_alert(self, signal: dict, lot_size: float, symbol: str) -> str:
        direction = signal['signal']
        entry = signal.get('entry_price', '—')
        sl = signal.get('sl', 0)
        tp = signal.get('tp', 0)
        strategy = signal.get('strategy', 'Unknown')
        
        lines = [
            f"🔔 <b>NEW SIGNAL: {symbol}</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"📈 <b>Strategy:</b> {strategy}",
            f"🎯 <b>Action:</b>   {'🟢 BUY' if direction == 'BUY' else '🔴 SELL'}",
            f"📝 <b>Reason:</b>   {signal.get('reason', '')}",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"💰 <b>Entry:</b>    {entry:.5f}" if isinstance(entry, float) else f"💰 <b>Entry:</b>    {entry}",
            f"🛑 <b>SL:</b>       {sl:.5f}",
            f"🏁 <b>TP:</b>       {tp:.5f}",
            f"📊 <b>Lot:</b>      {lot_size}",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"🕒 <b>Time:</b>     {datetime.now().strftime('%H:%M:%S')} (UTC)",
        ]
        return "\n".join(lines)

    def _telegram_confirm(self, alert_text: str, signal: dict, symbol: str) -> bool:
        callback_id = f"{symbol}_{int(time.time())}"
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Execute Trade", "callback_data": f"exec_{callback_id}"},
            {"text": "❌ Skip", "callback_data": f"skip_{callback_id}"}
        ]]}
        msg_id = self._send_telegram(alert_text, reply_markup=keyboard)
        if not msg_id: return self._console_confirm()
        return self._poll_telegram_callback(callback_id, msg_id)

    def _send_telegram(self, text: str, reply_markup: dict = None) -> int:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            import json
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            resp = requests.post(url, data=payload, timeout=10)
            data = resp.json()
            return data["result"]["message_id"] if data.get("ok") else 0
        except Exception: return 0

    def _answer_callback(self, callback_query_id: str):
        url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
        try: requests.post(url, data={"callback_query_id": callback_query_id}, timeout=5)
        except Exception: pass

    def _edit_message(self, msg_id: int, new_text: str):
        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        try: requests.post(url, data={"chat_id": self.chat_id, "message_id": msg_id, "text": new_text}, timeout=5)
        except Exception: pass

    def _flush_old_updates(self):
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        try:
            resp = requests.get(url, params={"offset": -1}, timeout=10)
            data = resp.json()
            results = data.get("result", [])
            if results: self._last_update_id = results[-1]["update_id"]
        except Exception: pass

    def _print_console_alert(self, text: str):
        print(f"\n{'='*50}\n{text}\n{'='*50}")

    def _console_confirm(self) -> bool:
        print(f"\nExecute this trade? [Y]es / [N]o  (auto-skip in {self.timeout}s)")
        result = [False]; input_received = threading.Event()
        def get_input():
            try:
                answer = input(">>> ").strip().upper()
                result[0] = answer in ("Y", "YES"); input_received.set()
            except EOFError: input_received.set()
        threading.Thread(target=get_input, daemon=True).start()
        input_received.wait(timeout=self.timeout)
        return result[0]

    def _play_sound(self):
        try:
            for _ in range(3):
                winsound.Beep(self.sound_freq, self.sound_duration)
                time.sleep(0.1)
        except Exception: pass
