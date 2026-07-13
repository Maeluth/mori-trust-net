from __future__ import annotations

import logging
from pathlib import Path

from telegram import Update, User
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from moritrustnet.config import Settings, load_settings
from moritrustnet.db import Database, UserRow
from moritrustnet.identity import format_user_card, snapshot_from_tg_user

log = logging.getLogger(__name__)


def _is_super(settings: Settings, user_id: int) -> bool:
    return user_id in settings.super_admin_ids


def _is_admin(db: Database, settings: Settings, user_id: int) -> bool:
    if _is_super(settings, user_id):
        return True
    row = db.admin_get(user_id)
    return row is not None and row.role in ("super", "admin")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    assert update.effective_user
    u = update.effective_user
    snap = snapshot_from_tg_user(u)
    prev, warnings = db.upsert_user_from_telegram(**snap)

    lines = [
        "Добро пожаловать в **MoriTrustNet**.",
        "",
        "Здесь фиксируются **отображаемое имя**, **@username** и **числовой id** — "
        "id в Telegram не меняется; по нему можно отличить смену ника или совпадения.",
        "",
        format_user_card(u),
    ]
    if prev and (
        prev.first_name != snap["first_name"]
        or (prev.username or "") != (snap["username"] or "")
    ):
        lines.append("")
        lines.append(
            "📝 **Изменение идентичности** по сравнению с прошлым визитом:\n"
            f"Было: {prev.first_name or '—'} | @{prev.username or '—'}\n"
            f"Стало: {snap['first_name'] or '—'} | @{snap['username'] or '—'}"
        )
    for w in warnings:
        lines.append("")
        lines.append(f"⚠️ {w}")

    if _is_super(settings, u.id):
        lines.append("")
        lines.append("Вы в списке **главных администраторов** (из настроек).")

    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ответ в стиле MORI GOD: профиль того, кто вызвал команду."""
    db: Database = context.application.bot_data["db"]
    assert update.effective_user
    u = update.effective_user
    snap = snapshot_from_tg_user(u)
    db.upsert_user_from_telegram(**snap)
    await update.effective_message.reply_text(
        format_user_card(u),
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "**Команды MoriTrustNet**\n\n"
        "/start — регистрация/обновление вашей карточки в сети\n"
        "/я или /me — ваш id и username (как в ответах «профиль»)\n"
        "/dossier &lt;запрос&gt; — поиск по id, @username или части имени\n"
        "/stats — агрегированная статистика\n"
        "/admin — панель администрирования (только админы)\n"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")


def _format_dossier_row(r: UserRow) -> str:
    un = f"@{r.username}" if r.username else "username не задан"
    flags = []
    if r.is_bot:
        flags.append("бот")
    if r.is_deleted_placeholder:
        flags.append("удалённый/заглушка")
    fl = f" ({', '.join(flags)})" if flags else ""
    name = " ".join(
        p for p in (r.first_name or "", r.last_name or "") if p
    ).strip() or "—"
    return f"• `{r.tg_user_id}` — {name}{fl} — {un}"


async def cmd_dossier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if not context.args:
        await update.effective_message.reply_text(
            "Укажите запрос: `/dossier 8018970561` или `/dossier @user` или `/dossier Иван`",
            parse_mode="Markdown",
        )
        return
    q = " ".join(context.args)
    rows = db.find_users(q)
    if not rows:
        await update.effective_message.reply_text("Ничего не найдено.")
        return
    body = "\n".join(_format_dossier_row(r) for r in rows)
    await update.effective_message.reply_text(
        f"**Досье (фрагмент)**\n\n{body}",
        parse_mode="Markdown",
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    s = db.stats()
    await update.effective_message.reply_text(
        "**Статистика**\n\n"
        f"Всего записей пользователей: {s['users_total']}\n"
        f"Помечено как боты: {s['bots']}\n"
        f"Удалённые/заглушки: {s['deleted_placeholders']}\n"
        f"Якорей в реестре: {s['anchors']}\n",
        parse_mode="Markdown",
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    assert update.effective_user
    uid = update.effective_user.id
    if not _is_admin(db, settings, uid):
        await update.effective_message.reply_text("Недостаточно прав.")
        return

    lines = [
        "**Панель администратора**\n",
        "`/admin list` — список админов",
        "`/admin audit` — последние действия",
        "`/admin anchors` — список якорей",
        "`/admin anchor_add <id> [заметка]` — назначить якорь",
        "`/admin anchor_remove <id>` — снять якорь",
    ]
    if _is_super(settings, uid):
        lines.append(
            "`/admin appoint <user_id>` — назначить админа\n"
            "`/admin revoke <user_id>` — снять админа (кроме супер-списка из .env)"
        )
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_admin_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    assert update.effective_user
    actor = update.effective_user
    if not _is_admin(db, settings, actor.id):
        await update.effective_message.reply_text("Недостаточно прав.")
        return

    if not context.args:
        await cmd_admin(update, context)
        return

    sub = context.args[0].lower()
    rest = context.args[1:]

    if sub == "list":
        rows = db.admin_list()
        supers = ", ".join(str(i) for i in sorted(settings.super_admin_ids))
        lines = [f"Супер-админы (env): {supers or '—'}", ""]
        for r in rows:
            lines.append(f"• `{r.tg_user_id}` — {r.role} (назначил: {r.appointed_by})")
        await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    if sub == "audit":
        items = db.recent_audit(25)
        if not items:
            await update.effective_message.reply_text("Записей аудита пока нет.")
            return
        lines = ["**Аудит**", ""]
        for it in items:
            payload = it.get("payload")
            extra = f" {payload}" if payload else ""
            lines.append(
                f"• `{it['actor_tg_user_id']}` — {it['action']}{extra}"
            )
        await update.effective_message.reply_text(
            "\n".join(lines)[:4000], parse_mode="Markdown"
        )
        return

    if sub == "anchors":
        rows = db.list_anchors(40)
        if not rows:
            await update.effective_message.reply_text("Якорей нет.")
            return
        lines = ["**Якоря**", ""]
        for r in rows:
            note = r.get("note") or ""
            lines.append(
                f"• `{r['tg_user_id']}` — @{r['username'] or '—'} — {r['first_name'] or ''} "
                f"(кто поставил: {r['set_by']}) {note}"
            )
        await update.effective_message.reply_text(
            "\n".join(lines)[:4000], parse_mode="Markdown"
        )
        return

    if sub == "anchor_add":
        if len(rest) < 1:
            await update.effective_message.reply_text(
                "Использование: `/admin anchor_add <user_id> [заметка]`",
                parse_mode="Markdown",
            )
            return
        target_id = int(rest[0])
        note = " ".join(rest[1:]) if len(rest) > 1 else None
        target_user = db.get_user(target_id)
        err = db.set_anchor(
            target_id=target_id,
            note=note,
            set_by=actor.id,
            eligible_check=target_user,
        )
        if err:
            await update.effective_message.reply_text(err)
            return
        db.audit_log(
            actor=actor.id,
            action="anchor_add",
            payload={"target": target_id, "note": note},
        )
        await update.effective_message.reply_text(
            f"Якорь `{target_id}` установлен.", parse_mode="Markdown"
        )
        return

    if sub == "anchor_remove":
        if len(rest) < 1:
            await update.effective_message.reply_text(
                "Использование: `/admin anchor_remove <user_id>`", parse_mode="Markdown"
            )
            return
        target_id = int(rest[0])
        ok = db.remove_anchor(target_id=target_id)
        db.audit_log(
            actor=actor.id,
            action="anchor_remove",
            payload={"target": target_id, "removed": ok},
        )
        await update.effective_message.reply_text(
            "Снято." if ok else "Такого якоря не было."
        )
        return

    if sub == "appoint":
        if not _is_super(settings, actor.id):
            await update.effective_message.reply_text("Только главный администратор.")
            return
        if len(rest) < 1:
            await update.effective_message.reply_text(
                "Использование: `/admin appoint <user_id>`", parse_mode="Markdown"
            )
            return
        new_id = int(rest[0])
        db.admin_upsert(tg_user_id=new_id, role="admin", appointed_by=actor.id)
        db.audit_log(
            actor=actor.id, action="appoint_admin", payload={"target": new_id}
        )
        await update.effective_message.reply_text(
            f"Пользователь `{new_id}` назначен админом.", parse_mode="Markdown"
        )
        return

    if sub == "revoke":
        if not _is_super(settings, actor.id):
            await update.effective_message.reply_text("Только главный администратор.")
            return
        if len(rest) < 1:
            await update.effective_message.reply_text(
                "Использование: `/admin revoke <user_id>`", parse_mode="Markdown"
            )
            return
        rid = int(rest[0])
        if rid in settings.super_admin_ids:
            await update.effective_message.reply_text(
                "Нельзя снять супер-админа из конфигурации через бота."
            )
            return
        db.admin_delete(rid)
        db.audit_log(actor=actor.id, action="revoke_admin", payload={"target": rid})
        await update.effective_message.reply_text("Готово.")
        return

    await update.effective_message.reply_text("Неизвестная подкоманда. См. /admin")


async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сохраняем пользователей из любых входящих апдейтов (личка/группы)."""
    db: Database = context.application.bot_data["db"]
    user: User | None = update.effective_user
    if user is None:
        return
    snap = snapshot_from_tg_user(user)
    db.upsert_user_from_telegram(**snap)


def build_application(db_path: Path | None = None) -> Application:
    settings = load_settings()
    path = db_path or Path(__file__).resolve().parent.parent / "data" / "moritrustnet.db"
    db = Database(path)

    app = Application.builder().token(settings.bot_token).build()
    app.bot_data["db"] = db
    app.bot_data["settings"] = settings

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("dossier", cmd_dossier))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("admin", cmd_admin_dispatch))

    # Кириллическая команда «я» — зарегистрируйте её в @BotFather: /setcommands
    app.add_handler(CommandHandler("я", cmd_me))

    for sid in settings.super_admin_ids:
        db.admin_ensure(tg_user_id=sid, role="super", appointed_by=None)

    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, log_all_updates),
        group=1,
    )
    return app
