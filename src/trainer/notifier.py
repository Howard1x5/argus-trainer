"""Telegram notification + approval commands."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class Notifier:
    """Sends notifications and polls for approval via Telegram."""

    def __init__(self, bot_token: str, chat_id: str):
        if not bot_token or not chat_id:
            logger.warning("Telegram not configured — notifications disabled")
            self._bot = None
            self._chat_id = None
            return
        self._bot = Bot(token=bot_token)
        self._chat_id = chat_id

    async def send(self, message: str) -> int | None:
        """Send a message, return message_id or None on failure."""
        if not self._bot:
            logger.info("[notify-disabled] %s", message)
            return None
        try:
            msg = await self._bot.send_message(
                chat_id=self._chat_id,
                text=message,
                parse_mode="Markdown",
            )
            return msg.message_id
        except TelegramError as e:
            logger.error("Telegram send failed: %s", e)
            return None

    async def send_cycle_start(self, case_name: str, cycle: int) -> int | None:
        return await self.send(
            f"*ARGUS Trainer* — Starting cycle {cycle}\n"
            f"Case: `{case_name}`"
        )

    async def send_score_update(
        self,
        case_name: str,
        cycle: int,
        iteration: int,
        score: float,
        prev_score: float | None,
        cost_usd: float,
    ) -> int | None:
        delta = ""
        if prev_score is not None:
            diff = score - prev_score
            arrow = "+" if diff >= 0 else ""
            delta = f" ({arrow}{diff:.1f}%)"

        return await self.send(
            f"*ARGUS Trainer* — Score Update\n"
            f"Case: `{case_name}` | Cycle {cycle}.{iteration}\n"
            f"Score: *{score:.1f}%*{delta}\n"
            f"Cost: ${cost_usd:.2f}"
        )

    async def send_approval_request(
        self,
        case_name: str,
        cycle: int,
        score: float,
        prev_score: float | None,
        cost_usd: float,
        fixes_summary: str,
    ) -> int | None:
        delta = ""
        if prev_score is not None:
            diff = score - prev_score
            arrow = "+" if diff >= 0 else ""
            delta = f" ({arrow}{diff:.1f}%)"

        return await self.send(
            f"*ARGUS Trainer* — Approval Required\n"
            f"Case: `{case_name}` | Cycle {cycle}\n"
            f"Score: *{score:.1f}%*{delta}\n"
            f"Cost: ${cost_usd:.2f}\n\n"
            f"Fixes:\n{fixes_summary}\n\n"
            f"Reply `/approve`, `/reject`, or `/skip`"
        )

    async def send_error(self, case_name: str, error: str) -> int | None:
        return await self.send(
            f"*ARGUS Trainer* — Error\n"
            f"Case: `{case_name}`\n"
            f"```\n{error[:500]}\n```"
        )

    async def send_complete(self, case_name: str, final_score: float, total_cost: float) -> int | None:
        return await self.send(
            f"*ARGUS Trainer* — Cycle Complete\n"
            f"Case: `{case_name}`\n"
            f"Final score: *{final_score:.1f}%*\n"
            f"Total cost: ${total_cost:.2f}"
        )

    async def poll_for_approval(
        self,
        state_file: Path,
        poll_interval: int = 60,
        timeout: int = 0,
    ) -> str:
        """Poll state file for approval status change.

        The Telegram bot (or manual CLI) writes the decision to state file.
        Returns: "approve", "reject", or "skip".
        """
        import json

        elapsed = 0
        while True:
            try:
                data = json.loads(state_file.read_text())
                status = data.get("status", "")
                if status == "APPROVED":
                    return "approve"
                elif status == "REJECTED":
                    return "reject"
                elif status == "SKIPPED":
                    return "skip"
            except (json.JSONDecodeError, FileNotFoundError):
                pass

            if timeout > 0 and elapsed >= timeout:
                logger.warning("Approval timeout after %ds", elapsed)
                return "reject"

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval


class TelegramApprovalBot:
    """Minimal Telegram bot that listens for /approve /reject /skip commands
    and writes the decision to the state file.

    Run this as a separate process alongside the orchestrator.
    """

    def __init__(self, bot_token: str, chat_id: str, state_file: Path):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.state_file = state_file

    async def run(self) -> None:
        """Start polling for commands."""
        import json

        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes

        async def _check_auth(update: Update) -> bool:
            return str(update.effective_chat.id) == self.chat_id

        async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            self._write_decision("APPROVED")
            await update.message.reply_text("Approved. Agent will commit and continue.")

        async def reject_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            self._write_decision("REJECTED")
            await update.message.reply_text("Rejected. Agent will revert changes.")

        async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            self._write_decision("SKIPPED")
            await update.message.reply_text("Skipped. Agent will move to next case.")

        async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not await _check_auth(update):
                return
            try:
                data = json.loads(self.state_file.read_text())
                status = data.get("status", "UNKNOWN")
                case = data.get("case_name", "none")
                cost = data.get("cost_usd", 0)
                await update.message.reply_text(
                    f"Status: {status}\nCase: {case}\nCost: ${cost:.2f}"
                )
            except (FileNotFoundError, json.JSONDecodeError):
                await update.message.reply_text("No active state found.")

        app = Application.builder().token(self.bot_token).build()
        app.add_handler(CommandHandler("approve", approve_cmd))
        app.add_handler(CommandHandler("reject", reject_cmd))
        app.add_handler(CommandHandler("skip", skip_cmd))
        app.add_handler(CommandHandler("status", status_cmd))

        logger.info("Telegram approval bot started")
        await app.run_polling(drop_pending_updates=True)

    def _write_decision(self, decision: str) -> None:
        """Write decision to state file."""
        import json

        try:
            data = json.loads(self.state_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data["status"] = decision
        self.state_file.write_text(json.dumps(data, indent=2))
        logger.info("Decision written: %s", decision)
