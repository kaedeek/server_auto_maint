import asyncio
import os
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv
from VersaLog import *

from sshclient import SSHClient

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
        
    @staticmethod
    def _get_int(name: str) -> int:
        value = os.getenv(name, "").strip()
        
        if not value:
            raise RuntimeError(f"Environment variable '{name}' is not set.")
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
            
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            logger.error("The specified channel does not support messages.")
            return
        
        for start in range(0, len(msg), 1900):
            await channel.send(msg[start:start + 1900])
        logger.info("Message sent successfully.")

    async def send_long_message(self, message: discord.Message, content: str) -> None:
        max_length = 1900
        
        for start in range(0, len(content), max_length):
            await message.reply(content[start:start + max_length])
        
    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user}")
        
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        
        if message.channel.id != self.channel_id:
            return
        
        if message.author.id not in self.allowed_user_ids:
            return
        
        content = message.content.strip().lower()
        
        if content == "status":
            await self._run_ssh_command(message, "status")
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
            await message.reply("アップグレードをキャンセルしました。")
            return
        
    async def _run_ssh_command(
            self,
            message: discord.Message,
            command: str
        ) -> None:
        
        await message.reply(f"`{command}` を実行しています……")
        
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
            
            await self.send_long_message(message, result)
            
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
            
    async def _request_upgrade_confirmation(
            self,
            message: discord.Message,
        ) -> None:
        
        self.pending_upgrade[message.author.id] = (
            time.monotonic() + self.upgrade_confirmation_timeout
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
        
        deadline = self.pending_upgrade.pop(message.author.id, None)
        if deadline is None or time.monotonic() > deadline:
            await message.reply(
                "有効なアップグレード確認がありません。"
                "先に `upgrade` と送信してください。"
            )
            return
        
        await self._run_ssh_command(message, "upgrade")