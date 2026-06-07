# デプロイ手順 — Kawanoさん NJSSモドキ（ランニングコスト 0 円）

このアプリは **Flask + SQLite だけ**で動く。データ更新（スクレイピング）は
**ローカルPCで `update.py`** を実行し、できた `denki_bid.db` を一緒にデプロイする。
→ デプロイ先（クラウド）は重いブラウザ処理を一切やらないので、**無料プランで十分**。

## 構成

| 役割 | どこで | コスト |
|---|---|---|
| Webアプリ（閲覧） | 無料ホスト（Render等） | **0円**（無料プラン） |
| データ更新（スクレイピング） | 自分のPC（`update.py`） | **0円**（電気代のみ） |
| データ保存 | SQLite ファイル（同梱） | **0円** |

## 手順A: Render.com 無料プラン（おすすめ・最も簡単）

1. このフォルダを GitHub にプッシュ（`denki_bid.db` も含める＝データ同梱）。
2. Render で「New + → Blueprint」、リポジトリを選択。`render.yaml` が自動で読まれる。
3. デプロイ完了。`https://kawano-njss-modoki.onrender.com` 等で公開。
   - 無料プランは無アクセス時スリープ（次アクセスで数秒の起動待ち）。**料金はかからない**。

## 手順B: Docker（任意のサーバ／ローカル）

```bash
docker build -t kawano-njss .
docker run -p 8000:8000 kawano-njss        # → http://localhost:8000
```

## 手順C: そのままローカル起動（デプロイ不要なら）

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # → http://127.0.0.1:5001
```

## データの更新フロー（無料）

```bash
# ローカルPCで実行（Playwrightが必要）
pip install -r requirements-local.txt
python -m playwright install chromium
python update.py --reset        # 最新データを denki_bid.db に取り込み

# 反映: 更新後の denki_bid.db を git commit & push すると、
#       次のデプロイで新しいデータが配信される（Renderは自動再デプロイ）。
```

## 環境変数（任意）

| 変数 | 用途 | 既定 |
|---|---|---|
| `PORT` | 待受ポート | 5001（ホストが自動設定） |
| `SECRET_KEY` | flashセッション用 | ローカル既定値 |
| `FLASK_DEBUG` | デバッグ（本番は0） | 1 |
