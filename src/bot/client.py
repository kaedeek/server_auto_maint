
from discord.ext import commands
from dotenv import load_dotenv
from VersaLog import *
from sshclient import SSHClient

import asyncio
import os
import re
import time
import discord

load_dotenv()

logger = VersaLog(
    enum="detailed",
    tag=["BASE", "CLIENT"],
    show_tag=True,
)

logger.add_webhook(
    url=os.getenv("url", ""),
    level="ERROR",
    format="discord",
)


class Client(commands.Bot):

    MONITOR_INTERVAL = 60
    MONITOR_THRESHOLD = 90.0

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

        self.token = os.getenv("Token")
        self.channel_id = self._get_int("channel_id")

        self.allowed_user_ids = {
            int(user_id.strip())
            for user_id in os.getenv("user_id", "").split(",")
            if user_id.strip()
        }

        if not self.allowed_user_ids:
            raise RuntimeError(
                "DISCORD_ALLOWED_USER_IDS must contain at least one user ID."
            )

        self.pending_upgrade: dict[int, float] = {}
        self.upgrade_confirmation_timeout = 60

        self.monitor_task: asyncio.Task | None = None
        self.monitor_alerts: set[str] = set()

    @staticmethod
    def _get_int(name: str) -> int:
        value = os.getenv(name, "").strip()

        if not value:
            raise RuntimeError(
                f"Environment variable '{name}' is not set."
            )

        try:
            return int(value)
        except ValueError as exc:
            raise RuntimeError(
                f"Environment variable '{name}' must be an integer."
            ) from exc

    async def send_msg(self, channel_id: int, msg: str) -> None:
        channel = self.get_channel(channel_id)

        if channel is None:
            channel = await self.fetch_channel(channel_id)

        if not isinstance(
            channel,
            (discord.TextChannel, discord.Thread),
        ):
            logger.error(
                "The specified channel does not support messages."
            )
            return

        for start in range(0, len(msg), 1900):
            await channel.send(msg[start:start + 1900])

        logger.info("Message sent successfully.")

    async def send_long_message(
        self,
        message: discord.Message,
        content: str,
    ) -> None:

        max_length = 1900

        for start in range(0, len(content), max_length):
            await message.reply(
                content[start:start + max_length]
            )

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user}")

        if (
            self.monitor_task is None
            or self.monitor_task.done()
        ):
            self.monitor_task = asyncio.create_task(
                self._monitor_loop()
            )

            logger.info("Automatic monitoring started.")

    async def close(self) -> None:
        if (
            self.monitor_task is not None
            and not self.monitor_task.done()
        ):
            self.monitor_task.cancel()

            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        await super().close()

    async def on_message(
        self,
        message: discord.Message,
    ) -> None:

        if message.author.bot:
            return

        if message.channel.id != self.channel_id:
            return

        if message.author.id not in self.allowed_user_ids:
            return

        content = message.content.strip().lower()

        if content == "monitor start":
            await self._start_monitor(message)
            return

        if content == "monitor stop":
            await self._stop_monitor(message)
            return

        if content == "monitor status":
            await self._monitor_status(message)
            return

        if content == "status":
            await self._run_ssh_command(message, "status")
            return

        if content == "security":
            await self._run_security_audit(message)
            return

        if content == "update":
            await self._run_ssh_command(message, "update")
            return

        if content == "upgrade":
            await self._request_upgrade_confirmation(message)
            return

        if content == "confirm upgrade":
            await self._confirm_upgrade(message)
            return

        if content == "cancel upgrade":
            self.pending_upgrade.pop(message.author.id, None)

            await message.reply(
                "アップグレードをキャンセルしました。"
            )
            return

    async def _run_ssh_command(
        self,
        message: discord.Message,
        command: str,
    ) -> None:

        await message.reply(
            f"`{command}` を実行しています……"
        )

        try:
            exit_code, output = await asyncio.to_thread(
                SSHClient().execute,
                command,
            )

            result = (
                f"**コマンド:** `{command}`\n"
                f"**終了コード:** `{exit_code}`\n"
                f"```text\n{output}\n```"
            )

            await self.send_long_message(
                message,
                result,
            )

            if exit_code != 0:
                logger.error(
                    f"SSH command '{command}' failed "
                    f"with exit code {exit_code}."
                )

        except Exception as exc:
            logger.error(
                f"SSH command '{command}' failed: "
                f"{type(exc).__name__}: {exc}"
            )

            await message.reply(
                f"SSHコマンド `{command}` の実行に失敗しました。\n"
                f"エラー種別: `{type(exc).__name__}`\n"
                f"詳細: `{str(exc)[:1000]}`"
            )

    async def _run_security_audit(
        self,
        message: discord.Message,
    ) -> None:

        await message.reply(
            "🔐 セキュリティ診断を実行しています……"
        )

        try:
            exit_code, output = await asyncio.to_thread(
                SSHClient().execute,
                "security",
            )

            hardening_index = "取得できませんでした"
            tests_performed = "取得できませんでした"

            warnings: list[str] = []
            suggestions: list[str] = []

            lines = output.splitlines()
            section = None

            for line in lines:
                line = line.strip()

                if "Warnings (" in line:
                    section = "warnings"
                    continue

                if "Suggestions (" in line:
                    section = "suggestions"
                    continue

                if section == "warnings" and line.startswith("!"):
                    warnings.append(
                        line.lstrip("!").strip()
                    )

                elif (
                    section == "suggestions"
                    and line.startswith("*")
                ):
                    suggestions.append(
                        line.lstrip("*").strip()
                    )

                if "Hardening index :" in line:
                    hardening_index = line.split(
                        ":", 1
                    )[1].strip()

                if "Tests performed :" in line:
                    tests_performed = line.split(
                        ":", 1
                    )[1].strip()

            result = (
                "🔐 **セキュリティ診断レポート**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 **セキュリティ強化指数：** `{hardening_index}`\n"
                f"🧪 **検査実施数：** `{tests_performed}`\n\n"
                f"⚠️ **警告：** `{len(warnings)} 件`\n"
                f"💡 **改善提案：** `{len(suggestions)} 件`\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )

            if warnings:
                result += "\n⚠️ **警告**\n"

                for warning in warnings:
                    result += f"• {warning}\n"

            if suggestions:
                result += "\n💡 **改善提案（先頭10件）**\n"

                for suggestion in suggestions[:10]:
                    result += f"• {suggestion}\n"

            result += (
                "\n📝 詳細はサーバーのLynisログを確認してください。"
            )

            await self.send_long_message(
                message,
                result,
            )

            if exit_code != 0:
                logger.error(
                    f"Lynis audit failed with exit code {exit_code}."
                )

        except Exception as exc:
            logger.error(
                f"Security audit failed: "
                f"{type(exc).__name__}: {exc}"
            )

            await message.reply(
                "❌ セキュリティ診断に失敗しました。\n"
                f"エラー: `{type(exc).__name__}`"
            )

    async def _start_monitor(
        self,
        message: discord.Message,
    ) -> None:

        if (
            self.monitor_task is not None
            and not self.monitor_task.done()
        ):
            await message.reply(
                "📊 自動監視はすでに稼働しています。"
            )
            return

        self.monitor_task = asyncio.create_task(
            self._monitor_loop()
        )

        await message.reply(
            "✅ 自動監視を開始しました。\n"
            f"監視間隔: `{self.MONITOR_INTERVAL}秒`\n"
            f"警告閾値: `{self.MONITOR_THRESHOLD}%`"
        )

        logger.info("Monitoring started manually.")

    async def _stop_monitor(
        self,
        message: discord.Message,
    ) -> None:

        if (
            self.monitor_task is None
            or self.monitor_task.done()
        ):
            await message.reply(
                "自動監視は停止しています。"
            )
            return

        self.monitor_task.cancel()

        try:
            await self.monitor_task
        except asyncio.CancelledError:
            pass

        self.monitor_task = None
        self.monitor_alerts.clear()

        await message.reply(
            "🛑 自動監視を停止しました。"
        )

        logger.info("Monitoring stopped.")

    async def _monitor_status(
        self,
        message: discord.Message,
    ) -> None:

        running = (
            self.monitor_task is not None
            and not self.monitor_task.done()
        )

        status = "🟢 稼働中" if running else "🔴 停止中"

        await message.reply(
            "📊 **自動監視ステータス**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"状態: {status}\n"
            f"監視間隔: `{self.MONITOR_INTERVAL}秒`\n"
            f"警告閾値: `{self.MONITOR_THRESHOLD}%`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    async def _monitor_loop(self) -> None:

        logger.info("Monitoring loop started.")

        try:
            while True:
                try:
                    exit_code, output = await asyncio.to_thread(
                        SSHClient().execute,
                        "monitor",
                        timeout=30,
                    )

                    if exit_code != 0:
                        logger.error(
                            "Monitoring command failed "
                            f"with exit code {exit_code}."
                        )

                    else:
                        metrics = self._parse_monitor_output(
                            output
                        )

                        await self._check_monitor_alerts(
                            metrics
                        )

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    logger.error(
                        f"Monitoring failed: "
                        f"{type(exc).__name__}: {exc}"
                    )

                await asyncio.sleep(
                    self.MONITOR_INTERVAL
                )

        except asyncio.CancelledError:
            logger.info("Monitoring loop cancelled.")
            raise

    @staticmethod
    def _parse_monitor_output(
        output: str,
    ) -> dict[str, float]:

        metrics: dict[str, float] = {}

        current_section = None

        for line in output.splitlines():

            line = line.strip()

            if line == "=== CPU ===":
                current_section = "cpu"
                continue

            if line == "=== MEMORY ===":
                current_section = "memory"
                continue

            if line == "=== DISK ===":
                current_section = "disk"
                continue

            if current_section == "cpu":

                match = re.search(
                    r"([\d.]+)\s*id",
                    line,
                )

                if match:
                    idle = float(match.group(1))
                    metrics["CPU"] = round(
                        100.0 - idle,
                        1,
                    )

            elif current_section == "memory":

                try:
                    value = float(line)

                    if 0 <= value <= 100:
                        metrics["MEMORY"] = round(
                            value,
                            1,
                        )

                except ValueError:
                    continue

            elif current_section == "disk":

                match = re.search(
                    r"(\d+(?:\.\d+)?)%",
                    line,
                )

                if match:
                    metrics["DISK"] = round(
                        float(match.group(1)),
                        1,
                    )

        return metrics

    async def _check_monitor_alerts(
        self,
        metrics: dict[str, float],
    ) -> None:

        if not metrics:
            logger.error(
                "Monitoring metrics could not be parsed."
            )
            return

        labels = {
            "CPU": "CPU使用率",
            "MEMORY": "メモリ使用率",
            "DISK": "ディスク使用率",
        }

        current_alerts = set()

        for name, value in metrics.items():

            if value >= self.MONITOR_THRESHOLD:

                current_alerts.add(name)

                if name in self.monitor_alerts:
                    continue

                alert = (
                    "🚨 **サーバー異常検知**\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ {labels[name]}: `{value}%`\n"
                    f"閾値: `{self.MONITOR_THRESHOLD}%`\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                )

                try:
                    await self.send_msg(
                        self.channel_id,
                        alert,
                    )

                    logger.warning(
                        f"{name} usage exceeded threshold: {value}%"
                    )

                except Exception as exc:
                    logger.error(
                        f"Failed to send monitoring alert: {exc}"
                    )

        recovered = self.monitor_alerts - current_alerts

        for name in recovered:

            value = metrics.get(name)

            if value is None:
                continue

            recovery = (
                "✅ **サーバー状態回復**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{labels[name]}が正常値に戻りました。\n"
                f"現在の使用率: `{value}%`\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )

            try:
                await self.send_msg(
                    self.channel_id,
                    recovery,
                )

            except Exception as exc:
                logger.error(
                    f"Failed to send recovery notification: {exc}"
                )

        self.monitor_alerts = current_alerts

    async def _request_upgrade_confirmation(
        self,
        message: discord.Message,
    ) -> None:

        self.pending_upgrade[message.author.id] = (
            time.monotonic()
            + self.upgrade_confirmation_timeout
        )

        await message.reply(
            "⚠️ **Ubuntu のパッケージをアップグレードしますか？**\n"
            "実行する場合は `confirm upgrade`、"
            "中止する場合は `cancel upgrade` と送信してください。\n"
            f"確認期限は {self.upgrade_confirmation_timeout} 秒です。"
        )

    async def _confirm_upgrade(
        self,
        message: discord.Message,
    ) -> None:

        deadline = self.pending_upgrade.pop(
            message.author.id,
            None,
        )

        if (
            deadline is None
            or time.monotonic() > deadline
        ):
            await message.reply(
                "有効なアップグレード確認がありません。"
                "先に `upgrade` と送信してください。"
            )
            return

        await self._run_ssh_command(
            message,
            "upgrade",
        )