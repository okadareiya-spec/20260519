"""ユーザー別・日次セッションの会話履歴を Upstash Redis で管理するモジュール。"""

import json
import logging
import os
from datetime import date
from typing import Any

from upstash_redis.asyncio import Redis

logger = logging.getLogger(__name__)

_redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"],
)

MAX_TURNS = 20
_MAX_HISTORY_ENTRIES = MAX_TURNS * 2  # user + assistant のペアで1ターン
_TTL_SECONDS = 60 * 60 * 24  # 24時間
_KEY_PREFIX = "lion:conv"


def _key(user_id: str) -> str:
    return f"{_KEY_PREFIX}:{user_id}:{date.today()}"


async def get_history(user_id: str) -> list[dict[str, Any]]:
    """当日セッションの会話履歴を返す。日付が変わっていれば空リストを返す。

    Args:
        user_id: LINE ユーザーID。

    Returns:
        当日の会話履歴。新セッションの場合は空リスト。
    """
    data = await _redis.get(_key(user_id))
    if data is None:
        return []
    return json.loads(data)


async def save_history(user_id: str, messages: list[dict[str, Any]]) -> None:
    """当日セッションの会話履歴を保存する。直近 MAX_TURNS ターンに切り詰める。

    Args:
        user_id: LINE ユーザーID。
        messages: 保存するメッセージリスト。
    """
    trimmed = messages[-_MAX_HISTORY_ENTRIES:]
    await _redis.set(
        _key(user_id),
        json.dumps(trimmed, ensure_ascii=False),
        ex=_TTL_SECONDS,
    )


async def clear_history(user_id: str) -> None:
    """当日セッションの会話履歴を削除する。ロール切り替え・会話終了時に使用。

    Args:
        user_id: LINE ユーザーID。
    """
    await _redis.delete(_key(user_id))


_ROLE_PREFIX = "lion:role"
_ROLE_TTL = 60 * 60 * 24 * 7  # ロールは1週間保持（日付またいでも維持）


def _role_key(user_id: str) -> str:
    return f"{_ROLE_PREFIX}:{user_id}"


async def get_role(user_id: str) -> str:
    """ユーザーの現在のロールを返す。未設定の場合は 'advisor'。

    Args:
        user_id: LINE ユーザーID。

    Returns:
        'advisor' または 'teacher'。
    """
    data = await _redis.get(_role_key(user_id))
    if data is None:
        return "advisor"
    return data


async def save_role(user_id: str, role: str) -> None:
    """ユーザーのロールを保存する。

    Args:
        user_id: LINE ユーザーID。
        role: 'advisor' または 'teacher'。
    """
    await _redis.set(_role_key(user_id), role, ex=_ROLE_TTL)


_NOTICE_PREFIX = "lion:notice"


def _notice_key(user_id: str) -> str:
    return f"{_NOTICE_PREFIX}:{user_id}"


async def has_seen_notice(user_id: str) -> bool:
    """ユーザーが利用案内を表示済みかどうかを返す。

    Args:
        user_id: LINE ユーザーID。

    Returns:
        表示済みなら True。
    """
    return bool(await _redis.exists(_notice_key(user_id)))


async def mark_notice_seen(user_id: str) -> None:
    """ユーザーの利用案内を表示済みにする（TTLなし・永続）。

    Args:
        user_id: LINE ユーザーID。
    """
    await _redis.set(_notice_key(user_id), "1")
