# ライオン先輩 LINE Bot

ライオン社コンサルタント向け業務相談Bot。Core of Core 8原則に基づいたアドバイスと、原則の解説を提供する。

---

## 技術スタック

| レイヤー | 技術 | 役割 |
|---|---|---|
| メッセージング | LINE Messaging API + リッチメニュー | ユーザーとのやりとり窓口 |
| Webサーバー | FastAPI + Uvicorn | Webhook受信・非同期処理 |
| AI | Claude API（claude-sonnet-4-6） | 回答文の生成 |
| 会話履歴 | Upstash Redis（REST API） | ユーザー別・日次セッション管理、ロール保持 |
| デプロイ | Render（Web Service） | 常時起動サーバー |

---

## ロール概要

Bot は2つのロールを持ち、リッチメニューで切り替えられる。

| ロール | 目的 | ウェルカムメッセージ |
|---|---|---|
| 相談役（advisor） | 業務上の悩みをヒアリングして解決策を提案する | 相談例付きの案内文 |
| 先生役（teacher） | Core of Core の各原則を説明する | 8原則の一覧と資料URL |

---

## メッセージ生成の仕組み

```
ユーザー（LINE）
    │  テキストメッセージ送信（リッチメニューのボタン含む）
    ▼
LINE Messaging API
    │  Webhook（HTTP POST）
    ▼
FastAPI /webhook エンドポイント
    │  1. HMAC-SHA256 署名検証
    │  2. イベント種別確認（message/text のみ処理）
    ▼
_handle_message()
    │  3. リッチメニューコマンドの判定
    │     SWITCH_TEACHER  → ロール切替（履歴リセット）＋先生役ウェルカム返信
    │     SWITCH_ADVISOR  → ロール切替（履歴リセット）＋相談役ウェルカム返信
    │     END_CONVERSATION → 履歴削除・返信なし
    │  4. Upstash Redis からロールと当日の会話履歴を取得
    │     会話キー: lion:conv:{user_id}:{YYYY-MM-DD}
    │     ロールキー: lion:role:{user_id}
    │     ※ 当日キーがなければ空リスト → ウェルカムメッセージ＋AI返答を同時送信
    │  5. ユーザー発言を履歴に追加
    ▼
Claude API（claude-sonnet-4-6）
    │  6. ロールに応じたシステムプロンプト＋会話履歴をまとめて送信
    │
    │  【相談役モードの回答フロー】
    │     フェーズⅠ：情報収集（最大6ターン、A/B形式）
    │       目的 / あるべき姿 / 現状の問題 / 原因 を収集
    │     フェーズⅡ：認識確認（4要素を提示して A/B で合意）
    │     フェーズⅢ：解決策提案（課題設定＋示唆＋アクション＋原則参照促し）
    │
    │  【先生役モードの回答フロー】
    │     原則の本質 → 考え方 → NG/OK例 → 資料URL＋ページ番号
    │
    ▼
_handle_message()（続き）
    │  7. CLOSE_SIGNAL 検知（「ありがとう」等でAIが出力）→ 返信スキップ
    │  8. 会話履歴を Redis に保存（TTL 24h、直近20ターンに切り詰め）
    ▼
LINE Messaging API（Reply API）
    │  9. ユーザーへ返信（新セッション時はウェルカム＋AI返答を1回で送信）
    ▼
ユーザー（LINE）
```

### 日次セッション管理

- Redisキーに日付を含める（`lion:conv:{user_id}:{YYYY-MM-DD}`）
- TTL を `_TTL_SECONDS`（24h = 86400秒）に設定
- 日付が変わると前日のキーは参照されず自動的に新セッション開始

### ロール管理

- ロールは `lion:role:{user_id}` キーで Redis に保存（TTL 7日間）
- 未設定の場合はデフォルトで相談役（advisor）
- ロール切り替え時は当日の会話履歴もリセットされる

### 会話終了検知

2つの終了パターンがある：

| パターン | トリガー | 動作 |
|---|---|---|
| リッチメニュー | `END_CONVERSATION` テキスト受信 | 履歴削除・返信なし |
| AIによる検知 | 「ありがとう」等のクローズサインを受けてAIが `CLOSE_CONVERSATION` を出力 | 返信スキップ |

---

## ファイル構成

```
lion-senpai-bot/
├── main.py                 # FastAPI アプリ + LINE Webhook ハンドラー
├── conversation.py         # Upstash Redis による会話履歴・ロール管理
├── system_prompt.py        # 定数ファサード（URL・ページ番号の更新はここ）
├── prompts/
│   ├── advisor.py          # 相談役システムプロンプト（3フェーズフロー）
│   └── teacher.py          # 先生役システムプロンプト＋ウェルカムメッセージ生成
├── rich_menu_setup.py      # リッチメニュー初期セットアップスクリプト（1回実行）
├── render.yaml             # Render デプロイ設定
├── requirements.txt
└── .env.example
```

---

## リッチメニューのセットアップ

### ボタン構成（2500×1686px）

```
┌──────────────┬──────────────┬──────────────┐
│   先生役      │   相談役      │  会話終了     │
│ SWITCH_TEACHER│ SWITCH_ADVISOR│END_CONVERSATI│
├──────────────┴──────────────┴──────────────┤
│              A              │      B        │
└─────────────────────────────┴───────────────┘
```

### セットアップ手順

1. 2500×1686 px の画像を `rich_menu_image.png` として配置
2. 環境変数 `LINE_CHANNEL_ACCESS_TOKEN` を設定
3. セットアップスクリプトを実行

```bash
python rich_menu_setup.py
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
| ロール | 相談役（advisor）/ 先生役（teacher）の2種類。リッチメニューで切り替え |
| 相談役の応答フロー | 6ターン情報収集（A/B質問）→ 認識確認 → 解決策提案 |
| 先生役の応答フロー | 原則の説明＋資料URL＋ページ番号 |
| 質問形式 | すべての質問は A/B 2択形式（リッチメニューで回答） |
| 会話終了 | リッチメニュー「会話終了」ボタン or クローズサイン検知 |
| 応答文字数 | 相談役フェーズⅢ：200〜400文字、先生役：300〜500文字 |
| 会話履歴 | 当日中のみ保持（日付をまたぐと新セッション） |
| 履歴上限 | 直近20ターン |
| ロール保持 | 1週間（日付またいでも維持） |
| エスカレーション | ハラスメント・コンプライアンス違反は定型文のみ返す |
| ストレージ | Upstash Redis（無料枠：10,000コマンド/日） |
