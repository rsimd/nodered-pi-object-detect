# ハンズオン実装契約: Raspberry Pi Node-RED物体検知

このAGENTS.mdだけを入力として、空の作業環境から同じ機能を再実装する。ほかの文書や既存資産を前提にしてはいけない。

## 1. 受講者が最初に設定する値

ユーザー名、IPアドレス、ホスト名は受講者ごとに異なるため、ソースコードや手順へ固定値を埋め込まない。最初に次の値を設定し、以後はプレースホルダーを使う。

```bash
export PI_USER="<Raspberry PiのLinuxユーザー名>"
export PI_HOST="<Raspberry PiのIPアドレスまたはホスト名>"
export PI_APP_DIR="/home/${PI_USER}/nodered-pi-object-detect"
export PI_NODE_RED_DIR="/home/${PI_USER}/.node-red"
export APP_URL="http://${PI_HOST}:1880/"
```

## 1.1 VS Code Remote Developmentで接続する

コマンドラインのSSHは使わず、VS CodeのRemote Development機能で作業する。

1. VS Codeに `Remote Development` 拡張パック、または `Remote - SSH` 拡張をインストールする。
2. コマンドパレットから `Remote-SSH: Connect to Host...` を選ぶ。
3. 接続先として `${PI_USER}@${PI_HOST}` を入力する。
4. 接続後のリモートウィンドウで、リモート側の `${PI_APP_DIR}` を開く。ディレクトリがなければ、VS Codeの統合ターミナルで作成してから開く。
5. ファイル編集、Node-RED導入、依存関係導入、テスト、サービス操作は、すべてリモートウィンドウのエクスプローラーと統合ターミナルで行う。

ローカルウィンドウのターミナルでPi向けコマンドを実行しない。sudoのパスワード入力が必要な場合は、リモートウィンドウの統合ターミナルで受講者が入力する。

ローカルでは、既存の作業ディレクトリとは別に新しいアプリケーションディレクトリを作成する。アプリ名は `nodered-pi-object-detect` とする。

## 2. 目的

Raspberry PiへNode-REDを導入し、USBカメラ映像を取得して軽量な物体検知を行う。検知結果を同一LANのWebブラウザへ表示し、画面に新しく登場した物体だけを保存する。

再実装後に提供するURLは次の形にする。

- `http://${PI_HOST}:1880/`:物体検知Web画面
- `http://${PI_HOST}:1880/red/`:Node-REDエディタ
- `http://${PI_HOST}:1880/api/health`:稼働状態API

## 3. 実装方針

- 作業は新規ディレクトリ内で行い、コード、設定、Web画面、テストをゼロから作る。
- Node-RED標準ノードで実現できる処理を優先する。
- 既存の標準ノードで安定した連続V4L2カメラ取得ができないため、カメラ取得だけをカスタムノードにする。
- ONNXモデルの推論、IoU追跡、イベント画像保存はカスタムノードから起動するPythonワーカーにする。
- 状態保存、HTTPルーティング、HTTPレスポンス、フロー接続はNode-RED標準ノードで行う。
- Web画面はNode-RED Dashboardへ置き換えず、静的HTML/CSS/JavaScriptをNode-REDの静的配信機能で公開する。これによりサムネイル一覧、モーダル大画像、最新画像更新を再現する。

## 4. Node-REDで表示する日本語名

画面に表示されるノード名、パレット名、カテゴリ名、入出力名、ヘルプ、ステータス、エラーは必ず日本語にする。内部のtype ID、npm名、Pythonモジュール名だけはASCIIでよい。

タブ名:

- `Pi物体検知`

カスタムノード:

| 表示名 | 内部type ID | npm名 |
|---|---|---|
| `USBカメラ映像` | `pi-camera-stream` | `node-red-contrib-pi-camera-stream` |
| `物体検知` | `pi-object-detector` | `node-red-contrib-pi-object-detector` |

パレットカテゴリは `カメラ・物体検知` とする。パレット表示名は `USBカメラ映像` と `物体検知カメラ` とする。

標準ノードの表示名:

1. `カメラ状態を保存`
2. `検知状態を保存`
3. `イベントを保存`
4. `検知エラーを保存`
5. `稼働状態`
6. `稼働状態JSON`
7. `稼働状態レスポンス`

## 5. Node-REDフロー

次の接続を再現する。

```text
USBカメラ映像 出力1 ─────> 物体検知 入力
USBカメラ映像 出力2 ─────> カメラ状態を保存
物体検知 出力1 ─────────> 検知状態を保存
物体検知 出力2 ─────────> イベントを保存
物体検知 出力3 ─────────> 検知エラーを保存
稼働状態 ─────> 稼働状態JSON ─────> 稼働状態レスポンス
```

`稼働状態` はGET要求を受け、フローコンテキストのカメラ状態・検知状態・エラーを `稼働状態JSON` でまとめ、`稼働状態レスポンス` から返す。

Node-RED設定は次の契約にする。

- エディタURL: `/red`
- HTTPノードのルート: `/api`
- 静的Webルート: `/`
- `/api/health` はHTTP 200を正常、503を異常とする
- 正常条件はカメラ状態が `running`、検知状態が `running`、カメラエラーと検知エラーがないこと

## 6. USBカメラ映像ノード

`pi-camera-stream` はカメラを連続取得し、1枚ずつJPEGフレームとしてNode-REDへ送る。

既定設定:

- カメラ種別:USB V4L2
- 既定デバイス: `/dev/video0`
- フォールバック: `/dev/video1`
- 解像度: `640x480`
- カメラ設定FPS: `15`
- ストリーム出力上限: `15 FPS`
- JPEG品質: `80`
- 起動時自動開始:有効
- 異常終了時自動再起動:有効、待機5秒

出力1のメッセージ:

- `msg.payload`:JPEG形式のNode.js `Buffer`
- `msg.topic`: `カメラ映像`
- `msg.contentType`: `image/jpeg`
- `msg.frame.format`: `jpeg`
- `msg.frame.timestamp`:ISO 8601時刻

出力2のメッセージ:

- `msg.topic`: `カメラ状態`
- `msg.payload.state`: `running`、`error`、`stopped` のいずれか
- `msg.payload.camera`:実際に開いたデバイス
- `msg.payload.fps`:実測取得FPS
- `msg.payload.frame_bytes`:JPEGサイズ
- `msg.payload.last_error`:エラー時の説明

カメラ取得ワーカーとNode.jsカスタムノード間の標準出力プロトコル:

- ヘッダーは1バイトの種別と4バイトのビッグエンディアン長
- 種別 `1`:JPEGフレーム
- 種別 `2`:JSON状態
- 種別 `3`:JSONエラー
- 最大パケットサイズ:5 MiB

## 7. 物体検知ノード

`pi-object-detector` は入力JPEGをPythonワーカーへ渡し、YOLO26n ONNX、追跡、イベント保存を行う。

推論ワーカーへの入力は `4バイトのビッグエンディアン長 + JPEGバイト列` とする。ワーカーは処理完了後に `ready` を返す。Node.js側は処理中にフレームを無制限に蓄積せず、常に最新フレームを1つだけ保持する。

出力:

1. `状態`:状態、FPS、推論時間、検出数、追跡数、イベント件数
2. `新規物体`:新規確定イベントのJSON
3. `エラー`:起動失敗、モデル失敗、入力失敗、ワーカー終了

## 8. 物体検知と新規判定

次の値を初期値として再現する。

- モデル:YOLO26n ONNX
- ONNX Runtime:CPUExecutionProvider
- 入力サイズ: `640`
- 信頼度閾値: `0.4`
- NMS IoU: `0.45`
- クラス:COCO 80クラス、既定は全クラス
- 追跡IoU: `0.3`
- 連続ヒット数: `3`
- 消失判定: `1.5秒`
- 保存上限: `500件`
- 保存期間: `7日`

同じクラスでIoUが閾値以上の検出を同一物体として追跡する。3フレーム連続で検出された時だけ新規イベントを確定する。1.5秒以上消失した後に再登場した場合は新規イベントとして扱う。

イベントは検出枠の周囲に余白を付けて保存する。大画像、横幅280px以下のサムネイル、一覧JSONを生成する。最新の注釈付きフレームは `latest.jpg` として上書きする。

イベント一覧JSONの各要素には少なくとも次を含める。

- `id`
- `label`
- `confidence`
- `timestamp`
- `bbox`
- 大画像URL
- サムネイルURL

## 9. Web画面

静的Web画面で次を表示する。

- 最新の注釈付きカメラ画像
- カメラFPSと推論時間
- 稼働中・異常・接続エラーの状態
- 新規物体の件数
- ラベル、信頼度、時刻付きのサムネイル一覧
- サムネイルクリック時の大画像モーダル

HTTP URL:

| URL | 内容 |
|---|---|
| `/` | 物体検知画面 |
| `/red/` | Node-REDエディタ |
| `/latest.jpg` | 最新プレビュー画像 |
| `/events/index.json` | イベント一覧JSON |
| `/events/{event_id}/image.jpg` | イベント大画像 |
| `/events/{event_id}/thumb.jpg` | イベントサムネイル |
| `/api/health` | 稼働状態JSON |

ブラウザの更新間隔:

- 最新画像:250 ms
- イベント一覧:1秒
- 稼働状態:1秒

## 10. モデル固定情報

モデルは次の固定URLから取得し、SHA256を検証する。

- URL: `https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.onnx`
- SHA256: `2e947b787d9e787b93a16772a5f55b1d4d8c4d86f53146149c5d6a642442d6f7`

検証に失敗したモデルは使用しない。モデルのライセンス条件を確認してから配布・利用する。

## 11. Piへの導入

Debian系Raspberry Pi向けのNode-RED公式インストール手順を使う。導入対象はNode.js、npm、Node-RED、Python venv、OpenCV、NumPy、ONNX Runtime、V4L2ツールである。

カメラ利用ユーザーをvideoグループへ追加し、ログインセッションを更新する。Node-REDは `nodered.service` で自動起動・自動再起動する。

Node-REDユーザーディレクトリは固定パスを使わず、サービスを実行するユーザーのホームディレクトリから求める。カスタムノードのインストール、設定、フロー配置、サービス再起動は、VS Codeのリモートウィンドウにある統合ターミナルから行う。

パスワード、秘密鍵、Node-RED認証情報をAGENTS.mdやソースへ書き込まない。sudoが必要な操作は、VS Codeのリモートウィンドウの統合ターミナルで実行する。

## 12. ハンズオン検証

実装後は次を順番に確認する。

1. Pythonの追跡ユニットテストを実行し、IoU、3回連続確定、再登場、同一クラス複数物体を確認する。
2. Pythonコンパイル、Node.js構文、Node-REDフローJSONを検査する。
3. `node-red --version` が表示されることを確認する。
4. `systemctl is-enabled nodered.service` が `enabled` であることを確認する。
5. `curl "http://${PI_HOST}:1880/api/health"` が正常時HTTP 200を返すことを確認する。
6. `/latest.jpg` がJPEGとして取得できることを確認する。
7. 同一LANのPCでWeb画面とNode-REDエディタを開く。
8. Node-REDパレットに `USBカメラ映像` と `物体検知カメラ` が日本語表示されることを確認する。
9. 静止した同一物体を映している間、イベント件数が無制限に増えないことを確認する。
10. 物体を画面外へ移動し、1.5秒以上経過後に再登場させ、新規イベントが1件だけ追加されることを確認する。
11. サムネイルをクリックして大画像モーダルが開くことを確認する。
12. 10分間連続稼働し、FPS、メモリ、イベント保存容量、Node-RED再起動の有無を記録する。

現在のPiでの参考値は、カメラ約6 FPS、検知約5 FPS、推論約200 ms、画像640x480である。これは機種、照明、カメラ、CPU負荷で変化するため、合否の固定値ではない。

## 13. 完了条件

- カメラ映像がNode-REDフローを通って物体検知へ届く。
- 新規物体だけが保存され、一覧と大画像がWeb画面に表示される。
- Node-REDの画面上のノード名が日本語である。
- username、IPアドレス、ホームディレクトリがプレースホルダーまたは環境変数であり、特定利用者に固定されていない。
- 既存コードに依存せず、AGENTS.mdだけを読んだ実装者がゼロから再現できる。
- LAN内公開を基本とし、外部公開時は認証、TLS、ファイアウォールを追加する。
