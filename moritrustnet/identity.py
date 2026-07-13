from __future__ import annotations

from telegram import User


def user_is_deleted_placeholder(user: User | None) -> bool:
    """
    «Deleted Account» в интерфейсе Telegram — не ник, а заглушка удалённого профиля.
    По полям User это обычно пустой username и характерное имя.
    """
    if user is None:
        return True
    fn = (user.first_name or "").strip()
    if fn.casefold() in ("deleted account", "deleted", "аккаунт удалён"):
        return True
    # Нет ни имени, ни username — часто так выглядят «пустые» отправители
    if not fn and not (user.username or "").strip():
        return True
    return False


def format_user_card(user: User | None) -> str:
    if user is None:
        return "Нет данных о пользователе."
    un = f"@{user.username}" if user.username else "username не задан"
    name_parts = [user.first_name or "", user.last_name or ""]
    display = " ".join(p for p in name_parts if p).strip() or "—"
    bot_mark = " 🤖 бот" if user.is_bot else ""
    del_mark = " ⚠️ удалённый/невалидный профиль" if user_is_deleted_placeholder(
        user
    ) else ""
    return (
        f"👤 Отображаемое имя: {display}{bot_mark}{del_mark}\n"
        f"🪪 User ID: `{user.id}`\n"
        f"📛 {un}"
    )


def snapshot_from_tg_user(user: User) -> dict:
    return {
        "tg_user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_bot": user.is_bot,
        "is_deleted_placeholder": user_is_deleted_placeholder(user),
    }
