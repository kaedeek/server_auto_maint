from dotenv import load_dotenv
from VersaLog import *

from bot.client import Client
from sshclient import SSHClient

import os

load_dotenv()

logger = VersaLog(
    enum="detailed",
    tag="BASE",
    show_tag=True,
)

logger.add_webhook(
    url=os.getenv("url", ""),
    level="ERROR",
    format="discord",
)


def main() -> None:
    client = Client()

    if not client.token:
        logger.error("Discord bot token is not configured.")
        raise RuntimeError("Environment variable 'Token' is not set.")

    client.run(client.token)


if __name__ == "__main__":
    main()