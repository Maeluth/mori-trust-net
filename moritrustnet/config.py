import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    super_admin_ids: frozenset[int]


def load_settings() -> Settings:
    token = os.getenv("MORITRUSTNET_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Задайте MORITRUSTNET_BOT_TOKEN в .env (см. .env.example). "
            "Токен из чата нужно отозвать в @BotFather и выпустить новый."
        )
    raw = os.getenv("MORITRUSTNET_SUPER_ADMIN_IDS", "").strip()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    if not ids:
        raise RuntimeError(
            "Задайте MORITRUSTNET_SUPER_ADMIN_IDS в .env — хотя бы один числовой user id."
        )
    return Settings(bot_token=token, super_admin_ids=frozenset(ids))
