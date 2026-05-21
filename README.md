# ライオン先輩 LINE Bot

ライオン社コンサルタント向け業務相談Bot。Core of Core 8原則に基づいたアドバイスを返す。

## 構成

```
lion-senpai-bot/
├── main.py            # FastAPI アプリ + LINE Webhook ハンドラー
├── conversation.py    # SQLite による会話履歴管理
├── system_prompt.py   # システムプロンプト（8原則を内包）
├── render.yaml        # Render デプロイ設定
├── requirements.txt
└── .env.example
```

## Render へのデプロイ手順

### 1. GitHubリポジトリの準備

```bash
git init
git add .
git commit -m "初回コミット"
# GitHubに新規リポジトリを作成し、プッシュ
git remote add origin https://github.com/your-org/lion-senpai-bot.git
git push -u origin main
```

### 2. Render でのセットアップ

1. [Render](https://render.com) にログイン
2. 「New +」→「Web Service」→ GitHubリポジトリを選択
3. render.yaml が自動検出される（または以下を手動設定）
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### 3. 環境変数の設定

Render ダッシュボードの「Environment」タブで以下を設定：

| 変数名 | 取得元 |
|--------|--------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers コンソール > チャネル > Messaging API |
| `LINE_CHANNEL_SECRET` | LINE Developers コンソール > チャネル基本設定 |
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com) |

### 4. Disk の確認

render.yaml に `disk` 設定が含まれている。SQLiteのDBファイルを `/data` にマウントするため、
Render のダッシュボードで Disk が正しく作成されていることを確認する。

### 5. LINE Webhook URL の設定

デプロイ完了後、RenderのサービスURLを確認して LINE Developers コンソールに設定：

```
Webhook URL: https://your-service-name.onrender.com/webhook
```

LINE Developers コンソール → チャネル → Messaging API → Webhook設定 → URLを入力 → 「検証」

## ローカル開発

```bash
# 依存ライブラリのインストール
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 環境変数の設定
cp .env.example .env
# .env を編集して実際のAPIキーを入力

# サーバー起動
uvicorn main:app --reload
```

ローカルでLINEからのWebhookを受け取るには、ngrok などのトンネルツールが必要：

```bash
ngrok http 8000
# 発行されたURLを LINE Developers の Webhook URL に設定
```

## 仕様

- **応答文字数**: 200〜400文字
- **会話履歴**: 同日中の連続会話（日付をまたぐと新セッション）
- **履歴上限**: 直近20ターン
- **エスカレーション**: ハラスメント・コンプライアンス違反は定型文のみ返す
- **クローズサイン検知**: 「ありがとう」「わかりました」等でBotが返信をスキップ
