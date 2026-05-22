# ライオン先輩 LINE Bot

ライオン社コンサルタント向け業務相談Bot。Core of Core 8原則に基づいたアドバイスを返す。

---

## 技術スタック

| レイヤー | 技術 | 役割 |
|---|---|---|
| メッセージング | LINE Messaging API | ユーザーとのやりとり窓口 |
| Webサーバー | FastAPI + Uvicorn | Webhook受信・非同期処理 |
| AI | Claude API（claude-sonnet-4-6） | 回答文の生成 |
| 会話履歴 | Upstash Redis（REST API） | ユーザー別・日次セッション管理 |
| デプロイ | Render（Web Service） | 常時起動サーバー |

---

## メッセージ生成の仕組み

```
ユーザー（LINE）
    │  テキストメッセージ送信
    ▼
LINE Messaging API
    │  Webhook（HTTP POST）
    ▼
FastAPI /webhook エンドポイント
    │  1. HMAC-SHA256 署名検証
    │  2. イベント種別確認（message/text のみ処理）
    ▼
_handle_message()
    │  3. Upstash Redis から当日の会話履歴を取得
    │     キー: lion:conv:{user_id}:{YYYY-MM-DD}
    │     ※ 当日キーがなければ空リスト → ウェルカムメッセージを送信
    │  4. ユーザー発言を履歴に追加
    ▼
Claude API（claude-sonnet-4-6）
    │  5. システムプロンプト（Core of Core 8原則 + 回答ルール）＋
    │     会話履歴をまとめて送信
    │  6. AIが3層構造で回答を生成
    │     ① 状況の言語化
    │     ② 原則に基づく示唆
    │     ③ 具体的なアクション提案 + Core of Core 参照促し
    ▼
_handle_message()（続き）
    │  7. CLOSE_SIGNAL 検知（「ありがとう」等）→ 返信スキップ
    │  8. 会話履歴を Redis に保存（TTL 24h、直近20ターンに切り詰め）
    ▼
LINE Messaging API（Reply API）
    │  9. ユーザーへ返信
    ▼
ユーザー（LINE）
```

### 日次セッション管理

- Redisキーに日付を含める（`lion:conv:{user_id}:2026-05-22`）
- TTL を 86400秒（24h）に設定
- 日付が変わると前日のキーは参照されず自動的に新セッション開始

### 会話終了検知

システムプロンプトで「ありがとう」「わかりました」等のクローズサインを受け取った場合は `CLOSE_CONVERSATION` を返すよう指示。Bot 側でこれを検知し、返信をスキップする。

---

## ファイル構成

```
lion-senpai-bot/
├── main.py            # FastAPI アプリ + LINE Webhook ハンドラー
├── conversation.py    # Upstash Redis による会話履歴管理
├── system_prompt.py   # システムプロンプト（8原則を内包）
├── render.yaml        # Render デプロイ設定
├── requirements.txt
└── .env.example
```

---

## Render へのデプロイ手順

### 1. Upstash Redis の作成（無料）

1. [https://upstash.com](https://upstash.com) でアカウント作成
2. 「Create Database」→ 以下で設定
   - Type: **Regional**
   - Region: **ap-northeast-1（Tokyo）**
   - TLS: ON
3. 作成後、「Details」タブで以下をコピーしておく
   - **REST URL** → `UPSTASH_REDIS_REST_URL` として使用
   - **REST Token** → `UPSTASH_REDIS_REST_TOKEN` として使用

### 2. GitHub リポジトリの準備

```bash
git init
git add .
git commit -m "初回コミット"
git remote add origin https://github.com/your-org/lion-senpai-bot.git
git push -u origin main
```

### 3. Render でのセットアップ

1. [Render](https://render.com) にログイン
2. 「New +」→「Web Service」→ GitHub リポジトリを選択
3. `render.yaml` が自動検出される（または以下を手動設定）
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### 4. 環境変数の設定

Render ダッシュボードの「Environment」タブで以下を設定：

| 変数名 | 取得元 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers → チャネル → Messaging API |
| `LINE_CHANNEL_SECRET` | LINE Developers → チャネル基本設定 |
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com) |
| `UPSTASH_REDIS_REST_URL` | Upstash コンソール → Details → REST URL |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash コンソール → Details → REST Token |

「Save Changes」後、自動デプロイが走る。

### 5. LINE Webhook URL の設定

デプロイ完了後、Render のサービス URL を確認して LINE Developers コンソールに設定：

```
Webhook URL: https://your-service-name.onrender.com/webhook
```

LINE Developers コンソール → チャネル → Messaging API → Webhook設定 → URL を入力 → 「検証」ボタンで疎通確認

---

## ローカル開発

```bash
# 依存ライブラリのインストール
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 環境変数の設定
cp .env.example .env
# .env を編集して各APIキーを入力

# サーバー起動
uvicorn main:app --reload
```

ローカルで LINE からの Webhook を受け取るには ngrok などのトンネルツールが必要：

```bash
ngrok http 8000
# 発行されたURLを LINE Developers の Webhook URL に設定
```

---

## 仕様サマリー

| 項目 | 内容 |
|---|---|
| 応答文字数 | 200〜400文字 |
| 会話履歴 | 当日中のみ保持（日付をまたぐと新セッション） |
| 履歴上限 | 直近20ターン |
| クローズサイン検知 | 「ありがとう」「わかりました」等でBot返信をスキップ |
| エスカレーション | ハラスメント・コンプライアンス違反は定型文のみ返す |
| ストレージ | Upstash Redis（無料枠：10,000コマンド/日） |
