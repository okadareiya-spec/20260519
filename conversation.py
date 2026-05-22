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


def _key(user_id: str) -> str:
    return f"lion:conv:{user_id}:{date.today()}"


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
        ex=86400,  # キーは24時間でTTL切れ（翌日は自動的に新セッション）
    )
