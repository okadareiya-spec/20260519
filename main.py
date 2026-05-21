"""ライオン先輩 LINE Bot - FastAPI Webhook サーバー。"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager

import anthropic
import httpx
from fastapi import FastAPI, HTTPException, Request, Response

import conversation as conv
from system_prompt import build_system_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
CLAUDE_MODEL = "claude-sonnet-4-6"
CLOSE_SIGNAL = "CLOSE_CONVERSATION"
WELCOME_MESSAGE = "何かあれば気軽に話しかけてください。"

anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
SYSTEM_PROMPT = build_system_prompt()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(conv.init_db)
    yield


app = FastAPI(lifespan=lifespan)


def _verify_signature(body: bytes, signature: str) -> bool:
    """LINE Webhook の署名を検証する。"""
    expected = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(
        base64.b64encode(expected).decode("utf-8"),
        signature,
    )


async def _call_claude(messages: list[dict]) -> str:
    """Claude API を非同期で呼び出して応答テキストを返す。"""
    response = await anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text.strip()


async def _reply_line(reply_token: str, text: str) -> None:
    """LINE Messaging API で返信する。"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(LINE_REPLY_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error("LINE reply failed: %s %s", resp.status_code, resp.text)


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    """LINE Webhook エンドポイント。"""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON body received")
        # LINEには200を返してリトライさせない
        return Response(content="OK", status_code=200)

    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        if event.get("message", {}).get("type") != "text":
            continue

        user_id = event.get("source", {}).get("userId")
        reply_token = event.get("replyToken")
        if not user_id or not reply_token:
            logger.warning("Skipping event without userId or replyToken")
            continue

        user_text = event["message"]["text"].strip()
        await _handle_message(user_id, reply_token, user_text)

    return Response(content="OK", status_code=200)


async def _handle_message(user_id: str, reply_token: str, user_text: str) -> None:
    """メッセージを処理し、必要に応じてLINEへ返信する。

    Args:
        user_id: LINE ユーザーID。
        reply_token: LINE リプライトークン。
        user_text: ユーザーのメッセージ本文。
    """
    history = await asyncio.to_thread(conv.get_history, user_id)

    # 当日の履歴がない場合は新セッション（日付をまたいだ初回）
    if not history:
        await _reply_line(reply_token, WELCOME_MESSAGE)
        # 相談内容はそのまま新セッションの最初のメッセージとして処理を続ける

    history.append({"role": "user", "content": user_text})

    try:
        reply_text = await _call_claude(history)
    except Exception as e:
        logger.error("Claude API error: %s", e)
        # ユーザー発言を保存せずにエラー返信（履歴の交互性を維持するため）
        history.pop()
        await asyncio.to_thread(conv.save_history, user_id, history)
        await _reply_line(reply_token, "少し時間をおいてから再度お試しください。")
        return

    # クローズサインを受け取った場合は返信せず待機
    # ユーザー発言も取り消して、次回会話が役割の交互性を保った状態で再開できるようにする
    if reply_text == CLOSE_SIGNAL or reply_text.startswith(CLOSE_SIGNAL):
        history.pop()  # 追加済みのユーザーメッセージを取り消す
        await asyncio.to_thread(conv.save_history, user_id, history)
        return

    history.append({"role": "assistant", "content": reply_text})
    await asyncio.to_thread(conv.save_history, user_id, history)
    await _reply_line(reply_token, reply_text)


@app.get("/health")
async def health() -> dict:
    """Render のヘルスチェック用エンドポイント。"""
    return {"status": "ok"}
