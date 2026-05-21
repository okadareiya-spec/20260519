"""ユーザー別・日次セッションの会話履歴をSQLiteで管理するモジュール。"""

import json
import logging
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_DIR = os.environ.get("DB_DIR")
if _DB_DIR is None:
    logger.warning(
        "DB_DIR が未設定です。データはデプロイのたびにリセットされます。"
        "Render Persistent Disk を設定することを推奨します。"
    )
DB_PATH = Path(_DB_DIR or ".") / "conversations.db"

MAX_TURNS = 20
_MAX_HISTORY_ENTRIES = MAX_TURNS * 2  # user + assistant のペアで1ターン


def _connect() -> sqlite3.Connection:
    """SQLiteデータベースへの接続を返す。

    Returns:
        sqlite3.Connection: データベース接続オブジェクト。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """テーブルが存在しない場合に作成する。"""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                user_id TEXT NOT NULL,
                session_date TEXT NOT NULL,
                messages TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (user_id, session_date)
            )
        """)


def get_history(user_id: str) -> list[dict[str, Any]]:
    """当日セッションの会話履歴を返す。日付が変わっていれば空リストを返す。

    Args:
        user_id: LINE ユーザーID。

    Returns:
        当日の会話履歴。新セッションの場合は空リスト。
    """
    today = str(date.today())
    with _connect() as conn:
        row = conn.execute(
            "SELECT messages FROM conversations WHERE user_id = ? AND session_date = ?",
            (user_id, today),
        ).fetchone()
    if row is None:
        return []
    return json.loads(row["messages"])


def save_history(user_id: str, messages: list[dict[str, Any]]) -> None:
    """当日セッションの会話履歴を保存する。直近 MAX_TURNS ターンに切り詰める。

    Args:
        user_id: LINE ユーザーID。
        messages: 保存するメッセージリスト。
    """
    today = str(date.today())
    trimmed = messages[-_MAX_HISTORY_ENTRIES:]
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversations (user_id, session_date, messages)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, session_date) DO UPDATE SET messages = excluded.messages
            """,
            (user_id, today, json.dumps(trimmed, ensure_ascii=False)),
        )
