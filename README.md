# Node-RED Raspberry Pi object detector

<img width="1121" height="565" alt="スクリーンショット 2026-08-25 17 13 27" src="https://github.com/user-attachments/assets/ca556c49-6dc7-4d1c-8e1f-584c659d397b" />

## はじめに

このrepositoryは、主催：岩手県 県南広域振興局，共催：北上川流域ものづくりネットワーク，事業実施：独立行政法人国立高等専門学校機構 一関工業高等専門学校，の「令和８年度ものづくり企業対象 ＤＸ人材育成プログラム」のIoT 機器活用編②〜③で利用したハンズオン資料です。
このハンズオンではRaspberry Pi 4 とカメラモジュール or USBカメラを活用し、物体検知を行うプログラムを作成します。また、リアルタイムでこれを監視するWeb UI機能と、特定のターゲットが画面に映った際にgmailでメールを送信する機能も作成します。これら全ての機能はCodexを活用したVibe Codingにて実装し、ハンズオン講義を通じて、受講者にはIoTデバイスの活用方法とVibe Codingのやり方の両方を学んでいただきます。


再現に必要な要件、構成、通信仕様、API、インストール、検証結果は、リポジトリ
ルートの [`AGENTS.md`](AGENTS.md) にまとめています。次回の実装では、この
AGENTS.mdを最初に読み、リポジトリルートで作業してください。

This project is intentionally independent of the existing projects in the parent directory.
It installs Node-RED on the Raspberry Pi and connects a custom USB camera stream node to a
Python YOLO26n ONNX detector node. The camera node emits JPEG `Buffer` messages, while the
Node-RED flow handles wiring, state, health, and web delivery.

## Target

- Ubuntu 24.04 on aarch64 Raspberry Pi
- USB camera `/dev/video0` by default, with `/dev/video1` as a configured fallback
- Node-RED editor at `/red`
- Application at `/`
- Application API below `/api`

## Node-RED flow

The flow is split into two custom nodes because the currently available camera nodes are
still-image helpers rather than a reliable continuous V4L2 source:

- `USBカメラ映像`: captures `/dev/video0` (with `/dev/video1` fallback) and emits one JPEG
  `msg.payload` Buffer per frame.
- `物体検知`: accepts those JPEG Buffers and sends only newly confirmed objects to the
  event-storage branch.

The detector node keeps only the latest frame while inference is busy, so slow inference
does not create an unbounded Node-RED message queue.

## Install on the Pi

Copy this directory to `/home/mriki/nodered-pi-object-detect/`, then run:

```bash
cd /home/mriki/nodered-pi-object-detect
bash scripts/install_pi.sh
```

The installer uses the official Node-RED Debian/Raspberry Pi installer, installs Python
dependencies, verifies the pinned model checksum, installs the local custom node, and
enables `nodered.service`.

After installation, open `http://<pi-ip>:1880/` from a computer on the same LAN.

## Verification

```bash
node-red --version
systemctl is-enabled nodered.service
curl http://127.0.0.1:1880/api/health
```

The live camera and inference checks are deliberately separate from the static build checks.

## Current implementation

The flow uses two small custom nodes where existing Node-RED nodes do not provide a suitable
continuous local V4L2 camera source or ONNX inference worker:

```text
USBカメラ映像 -- JPEG Buffer --> 物体検知 --> 状態・イベント・エラー
```

Node-RED core `function`, `http in`, and `http response` nodes handle state and health. The
web page is served by Node-RED's `httpStatic` setting and uses the files in `public/` for the
image preview, event list, and large-image dialog.
