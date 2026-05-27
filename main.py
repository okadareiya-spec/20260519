"""ライオン先輩 LINE Bot - FastAPI Webhook サーバー。"""

import base64
import hashlib
import hmac
import json
import logging
import os

import anthropic
import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response

import conversation as conv
from system_prompt import get_advisor_prompt, get_teacher_prompt, get_teacher_welcome

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
CLAUDE_MODEL = "claude-sonnet-4-6"
CLOSE_SIGNAL = "CLOSE_CONVERSATION"

# リッチメニューのボタンが送信するテキスト（大文字固定）
CMD_SWITCH_TEACHER = "SWITCH_TEACHER"
CMD_SWITCH_ADVISOR = "SWITCH_ADVISOR"
CMD_END_CONVERSATION = "END_CONVERSATION"

ADVISOR_WELCOME = (
    "おつかれさまです。今日の業務で迷ったことや、上司・クライアントとのやりとりで困ったことがあれば気軽に話しかけてください。\n"
    "例）「上司から急に競合調査を頼まれたが、何から始めればいいか分からない」\n"
    "例）「クライアントへの報告前にゴールが整理できていない」"
)

USAGE_NOTICE = (
    "【ご利用にあたって】\n"
    "・15分以上の無操作後の初回メッセージは返答が届かない場合があります。届かない場合は再送してください\n"
    "・会話履歴は当日中のみ保持されます（日付が変わると翌日に新セッション開始）\n"
    "・ロール切替（先生役↔相談役）を行うと当日の会話履歴がリセットされます\n"
    "・直近20ターンを超えると古い履歴から削除されます"
)

anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# 起動時に両ロールのプロンプトを生成しておく
ADVISOR_SYSTEM_PROMPT = get_advisor_prompt()
TEACHER_SYSTEM_PROMPT = get_teacher_prompt()
TEACHER_WELCOME = get_teacher_welcome()

app = FastAPI()


async def _with_notice(user_id: str, msgs: list[str]) -> list[str]:
    """ウェルカムメッセージ送信時、USAGE_NOTICE をまだ表示していなければ先頭メッセージに連結して返す。"""
    if not await conv.has_seen_notice(user_id):
        await conv.mark_notice_seen(user_id)
        return [msgs[0] + "\n\n" + USAGE_NOTICE] + msgs[1:]
    return msgs


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


async def _call_claude(messages: list[dict], system_prompt: str) -> str:
    """Claude API を非同期で呼び出して応答テキストを返す。"""
    response = await anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text.strip()


async def _reply_line(reply_token: str, texts: str | list[str]) -> None:
    """LINE Messaging API で返信する。texts はリストで複数バブル同時送信可能（最大5件）。"""
    if isinstance(texts, str):
        texts = [texts]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": t} for t in texts],
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(LINE_REPLY_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error("LINE reply failed: %s %s", resp.status_code, resp.text)


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """LINE Webhook エンドポイント。

    署名検証とイベント解析のみ同期的に行い、メッセージ処理はバックグラウンドに委譲して
    即座に 200 を返す。LINE は数秒以内に 200 を受け取らないとタイムアウトするため。
    """
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON body received")
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
        background_tasks.add_task(_handle_message, user_id, reply_token, user_text)

    return Response(content="OK", status_code=200)


async def _handle_message(user_id: str, reply_token: str, user_text: str) -> None:
    """メッセージを処理し、必要に応じてLINEへ返信する。

    Args:
        user_id: LINE ユーザーID。
        reply_token: LINE リプライトークン。
        user_text: ユーザーのメッセージ本文。
    """
    try:
        await _process_message(user_id, reply_token, user_text)
    except Exception as e:
        logger.error("unhandled error user_id=%s: %s", user_id, e, exc_info=True)


async def _process_message(user_id: str, reply_token: str, user_text: str) -> None:
    """_handle_message の実処理。BackgroundTask 内の全例外をここで発生させる。"""
    # --- リッチメニューコマンドの処理（Claude呼び出し不要）---
    if user_text == CMD_END_CONVERSATION:
        await conv.clear_history(user_id)
        return

    if user_text == CMD_SWITCH_TEACHER:
        await conv.clear_history(user_id)
        await conv.save_role(user_id, "teacher")
        await _reply_line(reply_token, await _with_notice(user_id, [TEACHER_WELCOME]))
        return

    if user_text == CMD_SWITCH_ADVISOR:
        await conv.clear_history(user_id)
        await conv.save_role(user_id, "advisor")
        await _reply_line(reply_token, await _with_notice(user_id, [ADVISOR_WELCOME]))
        return

    # --- 通常メッセージの処理 ---
    role = await conv.get_role(user_id)
    history = await conv.get_history(user_id)
    is_new_session = not history

    system_prompt = TEACHER_SYSTEM_PROMPT if role == "teacher" else ADVISOR_SYSTEM_PROMPT
    welcome = TEACHER_WELCOME if role == "teacher" else ADVISOR_WELCOME

    history.append({"role": "user", "content": user_text})

    try:
        reply_text = await _call_claude(history, system_prompt)
    except Exception as e:
        logger.error("Claude API error: %s", e)
        # ユーザー発言を保存せずにエラー返信（履歴の交互性を維持するため）
        history.pop()
        await conv.save_history(user_id, history)
        error_msg = "少し時間をおいてから再度お試しください。"
        msgs = [welcome, error_msg] if is_new_session else [error_msg]
        await _reply_line(reply_token, msgs)
        return

    # クローズサインを受け取った場合は返信せず待機
    # ユーザー発言も取り消して、次回会話が役割の交互性を保った状態で再開できるようにする
    if reply_text == CLOSE_SIGNAL or reply_text.startswith(CLOSE_SIGNAL):
        history.pop()  # 追加済みのユーザーメッセージを取り消す
        await conv.save_history(user_id, history)
        if is_new_session:
            await _reply_line(reply_token, welcome)
        return

    history.append({"role": "assistant", "content": reply_text})
    await conv.save_history(user_id, history)
    # 新セッション時はウェルカムメッセージとAI返答を1回のAPI呼び出しでまとめて送る
    # （Reply トークンは1回しか使えないため、分けて送ると2回目が 400 Invalid reply token になる）
    if is_new_session:
        await _reply_line(reply_token, await _with_notice(user_id, [welcome, reply_text]))
    else:
        await _reply_line(reply_token, reply_text)


@app.get("/health")
async def health() -> dict:
    """Render のヘルスチェック用エンドポイント。"""
    return {"status": "ok"}
