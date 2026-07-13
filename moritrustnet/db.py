from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass
class UserRow:
    tg_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_bot: bool
    is_deleted_placeholder: bool
    created_at: int
    updated_at: int


@dataclass
class AdminRow:
    tg_user_id: int
    role: str
    appointed_by: int | None
    appointed_at: int


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    tg_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_bot INTEGER NOT NULL DEFAULT 0,
                    is_deleted_placeholder INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
                CREATE INDEX IF NOT EXISTS idx_users_first_name ON users(first_name);

                CREATE TABLE IF NOT EXISTS identity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    recorded_at INTEGER NOT NULL,
                    FOREIGN KEY (tg_user_id) REFERENCES users(tg_user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_identity_user_time
                    ON identity_history(tg_user_id, recorded_at DESC);

                CREATE TABLE IF NOT EXISTS admins (
                    tg_user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL,
                    appointed_by INTEGER,
                    appointed_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS anchors (
                    tg_user_id INTEGER PRIMARY KEY,
                    note TEXT,
                    set_by INTEGER NOT NULL,
                    set_at INTEGER NOT NULL,
                    FOREIGN KEY (tg_user_id) REFERENCES users(tg_user_id)
                );

                CREATE TABLE IF NOT EXISTS admin_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_tg_user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_time ON admin_audit(created_at DESC);
                """
            )

    def upsert_user_from_telegram(
        self,
        *,
        tg_user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        is_bot: bool,
        is_deleted_placeholder: bool,
    ) -> tuple[UserRow | None, list[str]]:
        """
        Возвращает (предыдущая_строка_или_None, предупреждения).
        Предупреждения: конфликт ника/username с другим уже известным user id.
        """
        now = int(time.time())
        warnings: list[str] = []
        prev: UserRow | None = None
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,)
            ).fetchone()
            if row:
                prev = self._row_to_user(row)

            if not is_bot and not is_deleted_placeholder and first_name:
                dup = c.execute(
                    """
                    SELECT tg_user_id, username FROM users
                    WHERE first_name = ? AND tg_user_id != ? AND is_bot = 0
                      AND is_deleted_placeholder = 0
                    LIMIT 5
                    """,
                    (first_name, tg_user_id),
                ).fetchall()
                for r in dup:
                    warnings.append(
                        f"Тот же отображаемый ник «{first_name}» уже у user id {r['tg_user_id']}"
                        + (f" (@{r['username']})" if r["username"] else "")
                    )

            if username:
                dup_u = c.execute(
                    """
                    SELECT tg_user_id, first_name FROM users
                    WHERE username = ? COLLATE NOCASE AND tg_user_id != ?
                      AND is_bot = 0 AND is_deleted_placeholder = 0
                    LIMIT 5
                    """,
                    (username.lstrip("@"), tg_user_id),
                ).fetchall()
                for r in dup_u:
                    warnings.append(
                        f"Username @{username.lstrip('@')} уже привязан к user id {r['tg_user_id']}"
                        f" ({r['first_name'] or 'без имени'})"
                    )

            c.execute(
                """
                INSERT INTO users (
                    tg_user_id, username, first_name, last_name,
                    is_bot, is_deleted_placeholder, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tg_user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    is_bot = excluded.is_bot,
                    is_deleted_placeholder = excluded.is_deleted_placeholder,
                    updated_at = excluded.updated_at
                """,
                (
                    tg_user_id,
                    username,
                    first_name,
                    last_name,
                    1 if is_bot else 0,
                    1 if is_deleted_placeholder else 0,
                    prev.created_at if prev else now,
                    now,
                ),
            )
            c.execute(
                """
                INSERT INTO identity_history (
                    tg_user_id, username, first_name, last_name, recorded_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (tg_user_id, username, first_name, last_name, now),
            )
        return prev, warnings

    def _row_to_user(self, row: sqlite3.Row) -> UserRow:
        return UserRow(
            tg_user_id=int(row["tg_user_id"]),
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            is_bot=bool(row["is_bot"]),
            is_deleted_placeholder=bool(row["is_deleted_placeholder"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    def get_user(self, tg_user_id: int) -> UserRow | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,)
            ).fetchone()
            return self._row_to_user(row) if row else None

    def find_users(
        self, query: str, *, limit: int = 20
    ) -> list[UserRow]:
        q = query.strip()
        if not q:
            return []
        with self._conn() as c:
            if q.startswith("@"):
                q = q[1:]
            rows: list[sqlite3.Row] = []
            if q.isdigit():
                row = c.execute(
                    "SELECT * FROM users WHERE tg_user_id = ?", (int(q),)
                ).fetchone()
                if row:
                    rows = [row]
            if not rows:
                like = f"%{q}%"
                rows = c.execute(
                    """
                    SELECT * FROM users
                    WHERE username LIKE ? ESCAPE '\\'
                       OR first_name LIKE ? ESCAPE '\\'
                       OR last_name LIKE ? ESCAPE '\\'
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (like, like, like, limit),
                ).fetchall()
            return [self._row_to_user(r) for r in rows]

    def stats(self) -> dict[str, int]:
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            bots = c.execute(
                "SELECT COUNT(*) AS n FROM users WHERE is_bot = 1"
            ).fetchone()["n"]
            deleted_ph = c.execute(
                "SELECT COUNT(*) AS n FROM users WHERE is_deleted_placeholder = 1"
            ).fetchone()["n"]
            anchors = c.execute("SELECT COUNT(*) AS n FROM anchors").fetchone()["n"]
            return {
                "users_total": int(total),
                "bots": int(bots),
                "deleted_placeholders": int(deleted_ph),
                "anchors": int(anchors),
            }

    def is_anchor_eligible(self, u: UserRow) -> bool:
        return not u.is_bot and not u.is_deleted_placeholder

    def set_anchor(
        self,
        *,
        target_id: int,
        note: str | None,
        set_by: int,
        eligible_check: UserRow | None,
    ) -> str | None:
        if eligible_check is None:
            return "Пользователь не найден в базе (сначала пусть напишет боту /start)."
        if not self.is_anchor_eligible(eligible_check):
            return "Нельзя сделать якорем бота или «удалённый аккаунт»."
        now = int(time.time())
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO anchors (tg_user_id, note, set_by, set_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_user_id) DO UPDATE SET
                    note = excluded.note,
                    set_by = excluded.set_by,
                    set_at = excluded.set_at
                """,
                (target_id, note, set_by, now),
            )
        return None

    def remove_anchor(self, *, target_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM anchors WHERE tg_user_id = ?", (target_id,))
            return cur.rowcount > 0

    def list_anchors(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT a.tg_user_id, a.note, a.set_by, a.set_at,
                       u.username, u.first_name
                FROM anchors a
                JOIN users u ON u.tg_user_id = a.tg_user_id
                ORDER BY a.set_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def admin_get(self, tg_user_id: int) -> AdminRow | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM admins WHERE tg_user_id = ?", (tg_user_id,)
            ).fetchone()
            if not row:
                return None
            return AdminRow(
                tg_user_id=int(row["tg_user_id"]),
                role=row["role"],
                appointed_by=row["appointed_by"],
                appointed_at=int(row["appointed_at"]),
            )

    def admin_ensure(
        self, *, tg_user_id: int, role: str, appointed_by: int | None
    ) -> None:
        """Добавить админа, если записи ещё нет (не трогает appointed_at существующих)."""
        now = int(time.time())
        with self._conn() as c:
            c.execute(
                """
                INSERT OR IGNORE INTO admins (tg_user_id, role, appointed_by, appointed_at)
                VALUES (?, ?, ?, ?)
                """,
                (tg_user_id, role, appointed_by, now),
            )

    def admin_upsert(
        self, *, tg_user_id: int, role: str, appointed_by: int | None
    ) -> None:
        now = int(time.time())
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO admins (tg_user_id, role, appointed_by, appointed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_user_id) DO UPDATE SET
                    role = excluded.role,
                    appointed_by = excluded.appointed_by,
                    appointed_at = excluded.appointed_at
                """,
                (tg_user_id, role, appointed_by, now),
            )

    def admin_delete(self, tg_user_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM admins WHERE tg_user_id = ?", (tg_user_id,))
            return cur.rowcount > 0

    def admin_list(self) -> list[AdminRow]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM admins ORDER BY appointed_at ASC").fetchall()
            return [
                AdminRow(
                    tg_user_id=int(r["tg_user_id"]),
                    role=r["role"],
                    appointed_by=r["appointed_by"],
                    appointed_at=int(r["appointed_at"]),
                )
                for r in rows
            ]

    def audit_log(
        self, *, actor: int, action: str, payload: dict[str, Any] | None = None
    ) -> None:
        now = int(time.time())
        blob = json.dumps(payload, ensure_ascii=False) if payload else None
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO admin_audit (actor_tg_user_id, action, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (actor, action, blob, now),
            )

    def recent_audit(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM admin_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                if d.get("payload"):
                    try:
                        d["payload"] = json.loads(d["payload"])
                    except json.JSONDecodeError:
                        pass
                out.append(d)
            return out
