"""ライオン先輩Bot のリッチメニューをセットアップするスクリプト。

使用方法:
    1. rich_menu_image.png を本スクリプトと同じディレクトリに配置する（仕様は下記参照）
    2. 環境変数 LINE_CHANNEL_ACCESS_TOKEN を設定する
    3. python rich_menu_setup.py を実行する

画像仕様:
    サイズ: 2500 × 1686 px（LINE 推奨サイズ）
    形式: PNG または JPEG
    ファイル名: rich_menu_image.png

    レイアウト（ボタン配置イメージ）:
    ┌──────────────┬──────────────┬──────────────┐
    │              │              │              │
    │   先生役      │   相談役      │  会話終了     │
    │  (SWITCH     │  (SWITCH     │  (END_       │
    │  TEACHER)    │  ADVISOR)    │  CONVERS.)   │
    │              │              │              │
    ├──────────────┴──────────────┴──────────────┤ ← y=843
    │                              │              │
    │           A                  │      B       │
    │       (answer A)             │  (answer B)  │
    │                              │              │
    └──────────────────────────────┴──────────────┘
    Row1各列: 幅 833/834/833 × 高さ 843
    Row2左  : 幅 1250 × 高さ 843
    Row2右  : 幅 1250 × 高さ 843
"""

import os
import sys

import httpx

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
if not LINE_CHANNEL_ACCESS_TOKEN:
    print("ERROR: 環境変数 LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
    sys.exit(1)

_HEADERS = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

RICH_MENU_DEFINITION = {
    "size": {"width": 2500, "height": 1686},
    "selected": True,
    "name": "ライオン先輩メニュー",
    "chatBarText": "メニュー",
    "areas": [
        # Row 1 左: 先生役に切り替え
        {
            "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
            "action": {"type": "message", "text": "SWITCH_TEACHER"},
        },
        # Row 1 中: 相談役に切り替え
        {
            "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
            "action": {"type": "message", "text": "SWITCH_ADVISOR"},
        },
        # Row 1 右: 会話終了
        {
            "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
            "action": {"type": "message", "text": "END_CONVERSATION"},
        },
        # Row 2 左: A
        {
            "bounds": {"x": 0, "y": 843, "width": 1250, "height": 843},
            "action": {"type": "message", "text": "A"},
        },
        # Row 2 右: B
        {
            "bounds": {"x": 1250, "y": 843, "width": 1250, "height": 843},
            "action": {"type": "message", "text": "B"},
        },
    ],
}


def create_rich_menu(client: httpx.Client) -> str:
    """リッチメニューを作成し、richMenuId を返す。"""
    resp = client.post(
        "https://api.line.me/v2/bot/richmenu",
        headers=_HEADERS,
        json=RICH_MENU_DEFINITION,
    )
    resp.raise_for_status()
    rich_menu_id = resp.json()["richMenuId"]
    print(f"リッチメニュー作成完了: {rich_menu_id}")
    return rich_menu_id


def upload_image(client: httpx.Client, rich_menu_id: str, image_path: str) -> None:
    """リッチメニュー画像をアップロードする。"""
    content_type = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    with open(image_path, "rb") as f:
        resp = client.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            headers={**_HEADERS, "Content-Type": content_type},
            content=f.read(),
        )
    resp.raise_for_status()
    print("画像アップロード完了")


def set_default_rich_menu(client: httpx.Client, rich_menu_id: str) -> None:
    """リッチメニューを全ユーザーのデフォルトに設定する。"""
    resp = client.post(
        f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}",
        headers=_HEADERS,
    )
    resp.raise_for_status()
    print("デフォルトリッチメニュー設定完了")


def delete_all_rich_menus(client: httpx.Client) -> None:
    """既存のリッチメニューをすべて削除する（再セットアップ時に使用）。"""
    resp = client.get("https://api.line.me/v2/bot/richmenu/list", headers=_HEADERS)
    resp.raise_for_status()
    menus = resp.json().get("richmenus", [])
    for menu in menus:
        mid = menu["richMenuId"]
        client.delete(f"https://api.line.me/v2/bot/richmenu/{mid}", headers=_HEADERS)
        print(f"既存メニュー削除: {mid}")


def main() -> None:
    image_path = "rich_menu_image.png"
    if not os.path.exists(image_path):
        print(f"ERROR: {image_path} が見つかりません。")
        print("2500 × 1686 px の画像を用意して同じディレクトリに配置してください。")
        sys.exit(1)

    with httpx.Client(timeout=30.0) as client:
        print("既存のリッチメニューを削除中...")
        delete_all_rich_menus(client)

        print("リッチメニューを作成中...")
        rich_menu_id = create_rich_menu(client)

        print("画像をアップロード中...")
        upload_image(client, rich_menu_id, image_path)

        print("デフォルトメニューに設定中...")
        set_default_rich_menu(client, rich_menu_id)

    print("\nセットアップ完了。LINE でリッチメニューが表示されるか確認してください。")


if __name__ == "__main__":
    main()
