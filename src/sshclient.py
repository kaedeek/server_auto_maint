from VersaLog import *
from dotenv import dotenv_values
from pathlib import Path

import paramiko
import os
import shlex

logger = VersaLog(
enum="detailed",
tag=["BASE", "SSH CLIENT"],
show_tag=True,
)

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
ENV = dotenv_values(ENV_PATH)


class SSHClient:
    def __init__(self) -> None:
        self.host = str(ENV.get("ip") or "").strip()
        self.port = int(ENV.get("port") or "22")
        self.username = str(ENV.get("username") or "").strip()
        self.password = str(ENV.get("pass") or "")

        if not self.host:
            logger.error("SSH host is empty.")
            raise ValueError("SSH host is empty.")

        if not self.username:
            logger.error("SSH username is empty.")
            raise ValueError("SSH username is empty.")

        if not self.password:
            logger.error("SSH password is empty.")
            raise ValueError("SSH password is empty.")


    def execute(self, command: str, timeout: int = 60) -> tuple[int, str]:
        allowed_commands = {
            "status": (
                "printf '%s\\n' '=== CPU ==='; "
                "uptime; "
                "printf '%s\\n' '=== MEMORY ==='; "
                "free -h; "
                "printf '%s\\n' '=== DISK ==='; "
                "df -h /"
            ),

            "monitor": (
                "printf '%s\\n' '=== CPU ==='; "
                "top -bn1 | grep 'Cpu(s)'; "
                "printf '%s\\n' '=== MEMORY ==='; "
                "free | awk '/Mem:/ {printf \"%.1f\\n\", $3/$2*100}'; "
                "printf '%s\\n' '=== DISK ==='; "
                "df -P / | awk 'NR==2 {print $5}'"
            ),
            
            "update": "sudo -n apt-get update",
            "upgrade": "sudo -n apt-get upgrade -y",
            "security": "sudo lynis audit system --quick",
        }

        if command not in allowed_commands:
            logger.error("Unsupported command.")
            raise ValueError("Unsupported command.")

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

        try:
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=60,
                banner_timeout=60,
                auth_timeout=60,
                look_for_keys=False,
                allow_agent=False,
            )

            stdin, stdout, stderr = client.exec_command(
                allowed_commands[command],
                timeout=timeout,
                get_pty=False,
            )
            stdin.close()

            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()

            result = output
            if error:
                result += "\n[stderr]\n" + error

            return exit_code, result.strip() or "(出力なし)"

        finally:
            client.close()