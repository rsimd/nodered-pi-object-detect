#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
URL="https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.onnx"
EXPECTED="2e947b787d9e787b93a16772a5f55b1d4d8c4d86f53146149c5d6a642442d6f7"
TARGET="$ROOT/models/yolo26n.onnx"
mkdir -p "$ROOT/models"

if [[ -f "$TARGET" ]]; then
    ACTUAL="$(sha256sum "$TARGET" | awk '{print $1}')"
    if [[ "$ACTUAL" == "$EXPECTED" ]]; then
        echo "Model checksum verified: $TARGET"
        exit 0
    fi
    echo "Existing model checksum mismatch; downloading a fresh verified copy." >&2
fi

TEMP="$(mktemp "$ROOT/models/.yolo26n.XXXXXX")"
trap 'rm -f "$TEMP"' EXIT
curl --fail --location --retry 2 --output "$TEMP" "$URL"
ACTUAL="$(sha256sum "$TEMP" | awk '{print $1}')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
    echo "Model checksum mismatch: $ACTUAL" >&2
    exit 1
fi
mv "$TEMP" "$TARGET"
echo "Downloaded and verified: $TARGET"
