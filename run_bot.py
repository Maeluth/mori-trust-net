"""
Точка входа: `python run_bot.py`

Перед запуском:
1. Скопируйте .env.example → .env
2. Вставьте НОВЫЙ токен (тот, что был в чате, считайте скомпрометированным — /revoke в @BotFather)
3. Укажите MORITRUSTNET_SUPER_ADMIN_IDS
"""

from __future__ import annotations

import logging

from moritrustnet.bot_app import build_application

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)


def main() -> None:
    app = build_application()
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
