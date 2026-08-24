# Codex再現指示書: Raspberry Pi Node-RED物体検知

このファイルだけを読んで、`nodered-pi-object-detect/` の現在の機能を再現できるようにする。READMEや親ディレクトリの既存プロジェクトを前提にしてはいけない。

## 最重要ルール

- 作業対象はリポジトリ内の `nodered-pi-object-detect/` だけにする。
- `python-camera-monitor/`、`node-red-camera-app/`、親ディレクトリのモデル、画像、コード資産は使用しない。
- 必要なコードはゼロから `nodered-pi-object-detect/` に作成する。
- Node-REDの画面に表示されるノード名、パレット名、入出力名、説明、ステータスは日本語にする。
- 内部のNode-RED type ID、npmパッケージ名、Pythonモジュール名はASCIIの識別子でよいが、ユーザーが見る名称は日本語にする。
- 既存Node-REDノードで実現できる処理は優先して使い、連続V4L2カメラ取得とONNX推論・追跡だけをカスタムノードで実装する。
- 実装後は静的検査だけで完了とせず、Pi上のサービス、カメラ、HTTP API、Web画面を個別に確認する。

## 作業対象と配置

ローカルの実装ルート:

`nodered-pi-object-detect/`

Raspberry Piの配置先:

`/home/mriki/nodered-pi-object-detect/`

Piへの接続:

`ssh mriki@192.168.10.182`

親ディレクトリにある既存資産は、このアプリの再現に必要な情報源ではない。

## 現在の実装状態

対象環境は以下の状態を再現する。

- Raspberry Pi 5相当のaarch64 Ubuntu 24.04系
- Node.js `24.19.0`
- Node-RED `5.0.4`
- `nodered.service`: enabled、active running
- Python: venvを作り、system site packagesを利用
- OpenCV `4.6.0`
- NumPy `1.26.4`
- ONNX Runtime `1.29.0`
- USBカメラ `/dev/video0`。フォールバックは `/dev/video1`
- 解像度 `640x480`
- カメラ取得設定 `15 FPS`、ストリーム出力上限 `15 FPS`
- JPEG品質 `80`
- YOLO26n ONNX CPU推論上限 `5 FPS`

## Node-REDフローを完全に再現する

Node-REDタブ名は `Pi物体検知` とする。画面に表示するノード名は次の通りにする。

1. `USBカメラ映像`
2. `物体検知`
3. `カメラ状態を保存`
4. `検知状態を保存`
5. `イベントを保存`
6. `検知エラーを保存`
7. `稼働状態`
8. `稼働状態JSON`
9. `稼働状態レスポンス`

接続は次の通りにする。

```text
USBカメラ映像 出力1 ─────> 物体検知 入力
USBカメラ映像 出力2 ─────> カメラ状態を保存
物体検知 出力1 ─────────> 検知状態を保存
物体検知 出力2 ─────────> イベントを保存
物体検知 出力3 ─────────> 検知エラーを保存
稼働状態 ─────> 稼働状態JSON ─────> 稼働状態レスポンス
```

カスタムノードの内部type IDとnpmパッケージ名は以下の通りに固定する。

| 表示名 | type ID | npmパッケージ |
|---|---|---|
| USBカメラ映像 | `pi-camera-stream` | `node-red-contrib-pi-camera-stream` |
| 物体検知 | `pi-object-detector` | `node-red-contrib-pi-object-detector` |

パレットカテゴリは `カメラ・物体検知` とする。パレット表示名は `USBカメラ映像` と `物体検知カメラ` とする。出力名、ヘルプ、エラー、ノードステータスも日本語にする。

## カメラノード仕様

`pi-camera-stream` は `/dev/video0` をOpenCV V4L2で開き、JPEGフレームを連続出力する。既存の静止画用カメラノードへの置換はしない。静止画ノードではこのアプリのフレーム連続処理を再現できないためである。

- 出力1の `msg.payload`: JPEG形式のNode.js `Buffer`
- `msg.topic`: `カメラ映像`
- `msg.contentType`: `image/jpeg`
- `msg.frame.format`: `jpeg`
- 出力2の `msg.topic`: `カメラ状態`
- 状態には `state`、`camera`、`fps`、`frame_bytes`、`last_error` を含める
- 起動時自動開始、異常終了時5秒後自動再起動
- `/dev/video0` が開けなければ `/dev/video1` を試す

Pythonの `detector/camera_stream_worker.py` とNode.jsノード間の標準出力プロトコルは次の通りにする。

- 1バイト:パケット種別
- 4バイト:ビッグエンディアンのペイロード長
- 種別 `1`:JPEGフレーム
- 種別 `2`:JSON状態
- 種別 `3`:JSONエラー
- 最大パケットサイズ:5 MiB

## 物体検知ノード仕様

`pi-object-detector` はカメラノードからJPEG Bufferを受け取り、Pythonワーカー `detector.worker` を `--input-frames` で起動する。推論中は保留フレームを1つだけ保持し、古いフレームを捨てて最新フレームを送る。

Pythonワーカーへの入力は `4バイトのビッグエンディアン長 + JPEGバイト列` とする。処理完了時に `ready` を返し、Node.js側はその後に次のフレームを送る。

出力は次の3つとする。

1. `状態`:稼働状態、FPS、推論時間、検出数、追跡数、イベント件数
2. `新規物体`:新規確定イベントのJSON
3. `エラー`:起動失敗、カメラ、モデル、ワーカーのエラー

## 物体検知・追跡設定

`config/detector.json` に次の設定を保存する。

- モデル: `models/yolo26n.onnx`
- 入力サイズ: `640`
- 信頼度閾値: `0.4`
- NMS IoU: `0.45`
- クラス: COCO 80クラス、既定は全クラス
- 追跡IoU: `0.3`
- 連続ヒット数: `3`
- 消失時間: `1.5`秒
- 保存上限: `500`件
- 保存期間: `7`日

同じクラスでIoUが閾値以上の検出を同一物体として追跡する。3回連続で検出された時だけイベントを確定する。追跡が1.5秒を超えて消失した後に再登場した場合は、新しいイベントとして保存する。

イベントごとに次を保存する。

- `public/events/{event_id}/image.jpg`
- `public/events/{event_id}/thumb.jpg`
- `public/events/index.json` のラベル、信頼度、時刻、bbox、画像URL、サムネイルURL

最新の注釈付きフレームは `public/latest.jpg` に上書きする。

## Web画面とHTTP API

Node-REDの `settings.js` で `public/` を `/` に静的公開し、`httpNodeRoot` を `/api` とする。Dashboardノードへ置き換えず、現在のHTML/CSS/JavaScript画面を再現する。

| URL | 内容 |
|---|---|
| `/` | 物体検知Web画面 |
| `/red/` | Node-REDエディタ |
| `/latest.jpg` | 最新プレビュー |
| `/events/index.json` | イベント一覧 |
| `/events/{event_id}/image.jpg` | イベント大画像 |
| `/events/{event_id}/thumb.jpg` | イベントサムネイル |
| `/api/health` | カメラ・検知状態JSON |
| `/api/health`のフローURL | `/health` |

Web画面は `public/app.js` が次を定期取得する。

- `/latest.jpg`:250 ms間隔
- `/events/index.json`:1秒間隔
- `/api/health`:1秒間隔

イベントサムネイルのクリックで `<dialog>` モーダルを開き、大画像とラベル・信頼度・時刻を表示する。

## 必須ファイル構成

```text
nodered-pi-object-detect/
├── AGENTS.md
├── README.md
├── .gitignore
├── config/detector.json
├── detector/
│   ├── camera.py
│   ├── camera_stream_worker.py
│   ├── model.py
│   ├── requirements.txt
│   ├── storage.py
│   ├── tracking.py
│   └── worker.py
├── model-manifest.json
├── node-red-contrib-pi-camera-stream/
│   ├── package.json
│   ├── pi-camera-stream.html
│   └── pi-camera-stream.js
├── node-red-contrib-pi-object-detector/
│   ├── package.json
│   ├── pi-object-detector.html
│   └── pi-object-detector.js
├── nodered/
│   ├── flows.json
│   └── settings.js
├── public/
│   ├── app.js
│   ├── index.html
│   └── style.css
├── scripts/
│   ├── download_model.sh
│   └── install_pi.sh
└── tests/test_tracking.py
```

## Piへのインストール・更新

```bash
cd /home/mriki/nodered-pi-object-detect
bash scripts/install_pi.sh
```

インストーラーはDebian系向けのNode-RED公式インストーラーを使い、Node-RED、Python依存関係、モデル、設定、2つのローカルnpmノードを配置し、`nodered.service` を有効化する。モデルURLとSHA256は `model-manifest.json` と `scripts/download_model.sh` で固定する。

手動更新時は次を行う。

```bash
cd /home/mriki/nodered-pi-object-detect
install -m 0644 nodered/settings.js /home/mriki/.node-red/settings.js
install -m 0644 nodered/flows.json /home/mriki/.node-red/flows.json
cd /home/mriki/.node-red
npm install --no-save --install-links \
  /home/mriki/nodered-pi-object-detect/node-red-contrib-pi-camera-stream \
  /home/mriki/nodered-pi-object-detect/node-red-contrib-pi-object-detector
sudo systemctl restart nodered.service
```

## モデル固定情報

- URL: `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.onnx`
- SHA256: `2e947b787d9e787b93a16772a5f55b1d4d8c4d86f53146149c5d6a642442d6f7`
- 配置先: `models/yolo26n.onnx`
- モデルはGit管理対象外とし、取得時にSHA256を検証する。

## 検証手順と現在の基準値

ローカル検証:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q detector
node --check node-red-contrib-pi-camera-stream/pi-camera-stream.js
node --check node-red-contrib-pi-object-detector/pi-object-detector.js
```

Pi検証:

```bash
node-red --version
systemctl is-enabled nodered.service
curl http://127.0.0.1:1880/api/health
```

現在確認できている基準値:

- Node-RED `5.0.4`、Node.js `24.19.0`
- サービス `active`、`enabled`
- LANから `/`、`/red/`、`/api/health` へ到達
- `/api/health` HTTP 200、カメラ・検知エラーなし
- カメラ約6.3 FPS、検知約4.8 FPS、推論約200 ms
- `latest.jpg` は640x480 JPEG
- Node-REDパレットに日本語の `USBカメラ映像` と `物体検知カメラ` を表示
- 10秒間のNode-RED RSS確認は約141,584 KiBから141,840 KiB

10分間連続稼働、CSIカメラ実機、同一物体の再登場を含む実カメラシナリオは追加検証項目であり、上の短時間確認を10分間試験済みとは扱わない。

## セキュリティと運用

- Node-REDエディタはLAN内利用を前提とする。外部公開時は認証、TLS、ファイアウォールを追加する。
- `public/events/`、`public/latest.jpg`、`models/*.onnx`、`.venv/`、`__pycache__/` はGit管理対象外にする。
- UbuntuではRaspberry Pi GPIOノードが非アクティブになる場合があるが、USBカメラ物体検知には影響しない。
- 既存プロジェクトをコピーして仕様を満たしたことにしてはいけない。上記ファイルと機能を対象ディレクトリ内で再実装する。
