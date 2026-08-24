# Raspberry Pi Node-RED物体検知アプリ仕様書

## 1. 文書情報

- 対象: `nodered-pi-object-detect`
- 作成日: 2026-08-24
- 対象機器: Raspberry Pi 4/5相当、Ubuntu/Debian系、aarch64
- 設置カメラ: USB V4L2カメラ。既定値は `/dev/video0`、切替候補は `/dev/video1`

## 2. 目的と範囲

Raspberry Pi上でNode-REDを常駐させ、カメラ映像から軽量な物体検知を行う。検知結果は同一LAN上のWebブラウザから確認できるようにし、画面上に新しく登場した物体だけを画像として保存する。

本プロジェクトは親ディレクトリにある既存プロジェクトとは独立しており、既存のカメラ監視コードやモデルは使用しない。

## 3. 機能要件

1. USBカメラから連続映像を取得する。
2. JPEGフレームをNode-REDメッセージとして後段へ渡す。
3. YOLO26n ONNXをONNX Runtimeで実行する。
4. クラス名とIoUを用いて検出物体を追跡する。
5. 3フレーム連続検出後に物体を確定する。
6. 1.5秒以上消失した物体の再登場を新規物体として扱う。
7. 新規物体の画像、サムネイル、ラベル、信頼度、時刻を保存する。
8. 最新の注釈付き画像を `latest.jpg` として更新する。
9. イベント一覧をWeb画面の下部に表示する。
10. サムネイルをクリックすると大画像をモーダル表示する。
11. 同一LAN上のPCからWeb画面とNode-REDエディタを閲覧できるようにする。

## 4. 非機能要件

- Node-REDはsystemdの `nodered.service` で自動起動する。
- 推論中にフレームを無制限にキューへ蓄積しない。検知ノードは最新フレームだけを保持する。
- イベント画像は最大500件、保存期間は7日間とする。
- JPEG、JSON、設定の書き込みは一時ファイル経由の置換で行い、途中状態を公開しにくくする。
- モデルファイルは固定URLとSHA256で検証する。
- Node-RED標準ノードで状態保存、HTTP公開、フロー制御を行い、既存ノードで代替しにくいカメラ連続取得と推論だけをカスタムノードで担当する。

## 5. システム構成

```text
[USBカメラ /dev/video0]
          |
          v
[USBカメラ映像ノード]
  JPEG Bufferを出力
          |
          v
[物体検知ノード]
  YOLO26n + IoU追跡
          |
     +----+-----+
     |          |
     v          v
[状態保存]  [イベント保存]
     |
     v
[HTTP稼働状態]

[Node-RED httpStatic]
          |
          v
       [Web画面]
```

### 5.1 Node-REDノード

#### USBカメラ映像 `pi-camera-stream`

- USB V4L2カメラをPythonワーカーで取得する。
- 出力1: `msg.payload` にJPEG形式のNode.js `Buffer`、`msg.contentType` に `image/jpeg`
- 出力2:カメラ状態、FPS、エラー情報
- 設定は `config/detector.json` の `camera` セクションで行う。
- カメラワーカー異常終了時は5秒後に再起動する。

#### 物体検知 `pi-object-detector`

- 入力のJPEG `Buffer`を最新フレーム優先でPythonワーカーへ渡す。
- 出力1:推論状態
- 出力2:新規物体イベント
- 出力3:エラー
- モデルロード、推論、追跡、イベント画像保存はこのノードから起動するPythonワーカーが担当する。

#### Node-RED標準ノード

- `function`:カメラ状態、検知状態、イベント、エラーをフローコンテキストへ保存する。
- `http in`: `/api/health` の要求を受ける。
- `function`:カメラと検知の状態をJSON化する。
- `http response`:稼働状態JSONを返す。

## 6. 画像処理・通信仕様

カメラワーカーとNode-REDノード間は、標準出力上のバイナリパケットを使う。

- ヘッダー: 1バイトの種別 + 4バイトのビッグエンディアン長
- 種別 `1`:JPEGフレーム
- 種別 `2`:JSON形式の状態
- 種別 `3`:JSON形式のエラー
- 最大パケットサイズ:5 MiB

物体検知ワーカーへの入力は、4バイトのビッグエンディアン長に続くJPEGバイト列とする。処理完了後に `ready` を返し、Node-RED側が次の最新フレームを送る。

## 7. 物体検知仕様

- モデル: YOLO26n ONNX
- 実行プロバイダー: ONNX Runtime CPUExecutionProvider
- 入力サイズ:640
- 信頼度閾値:0.4
- NMS IoU:0.45
- 推論上限:5 FPS
- 追跡IoU:0.3
- 確定条件:3回の連続ヒット
- 消失判定:1.5秒
- ラベル:COCO 80クラス

イベント画像は検出枠の周囲に余白を付けたJPEGとして保存し、横幅280px以下のサムネイルも生成する。

## 8. Web画面・HTTP API

| URL | 内容 |
|---|---|
| `/` | 物体検知Web画面 |
| `/red/` | Node-REDエディタ |
| `/latest.jpg` | 最新の注釈付き画像 |
| `/events/index.json` | イベント一覧JSON |
| `/events/{event_id}/image.jpg` | イベント大画像 |
| `/events/{event_id}/thumb.jpg` | イベントサムネイル |
| `/api/health` | カメラ・検知状態JSON |

Web画面は `public/app.js` が一定間隔で `/latest.jpg`、`/events/index.json`、`/api/health` を取得する。表示レイアウトやモーダルはHTML/CSS/JavaScriptで実装し、Node-REDは静的ファイルを `httpStatic` で公開する。

## 9. 配置とインストール

### ローカル

プロジェクトの作業ディレクトリ:

`/Users/mriki/Documents/ChatGPT/DX2026/nodered-pi-object-detect/`

### Raspberry Pi

配置先:

`/home/mriki/nodered-pi-object-detect/`

インストーラー:

```bash
cd /home/mriki/nodered-pi-object-detect
bash scripts/install_pi.sh
```

インストーラーはNode-RED、Python依存関係、モデル、設定、2つのカスタムノードを準備し、`nodered.service` を有効化する。

## 10. モデル管理

- URL: `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.onnx`
- SHA256: `2e947b787d9e787b93a16772a5f55b1d4d8c4d86f53146149c5d6a642442d6f7`
- 配置先: `models/yolo26n.onnx`
- モデルはGit管理対象外とし、`scripts/download_model.sh` で取得・検証する。

## 11. 検証結果

2026-08-24時点で、Raspberry Pi上で次を確認済み。

- Node-RED `5.0.4`、Node.js `24.19.0`
- `nodered.service`: `active`、`enabled`
- LANから `/`、`/red/`、`/api/health` へ到達
- `/api/health`:HTTP 200、カメラ・検知エラーなし
- カメラ取得:約6.3 FPS
- 検知処理:約4.8 FPS、推論時間約200 ms
- 最新画像:JPEG 640x480
- Node-REDパレットに「USBカメラ映像」「物体検知」を表示
- 10秒間のRSS確認: Node-REDプロセス約141,584 KiBから141,840 KiB
- Python追跡ユニットテスト4件、JavaScript構文検査、設定JSON検査に成功

10分間連続稼働試験、CSIカメラ実機試験、同一物体の再登場シナリオの実カメラ試験は今後の追加確認項目とする。

## 12. 運用上の注意

- Node-REDエディタはLAN内公開を前提とする。外部公開する場合は認証、TLS、ファイアウォールを追加する。
- Ubuntu上ではRaspberry Pi GPIOノードが非アクティブになる場合があるが、本アプリのUSBカメラ処理には影響しない。
- `public/events/`、`public/latest.jpg`、仮想環境、モデルは実行時生成物としてGit管理対象外とする。
