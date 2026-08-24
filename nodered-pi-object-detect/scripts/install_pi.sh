#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_RED_DIR="$HOME/.node-red"

if [[ "$(uname -m)" != "aarch64" ]]; then
    echo "Warning: this installer targets aarch64 Raspberry Pi; detected $(uname -m)." >&2
fi

sudo apt-get update
sudo apt-get install -y build-essential curl git python3-venv python3-opencv python3-numpy python3-pip v4l-utils

if ! command -v node-red >/dev/null 2>&1; then
    bash <(curl -fsSL https://github.com/node-red/linux-installers/releases/latest/download/install-update-nodered-deb)
fi

python3 -m venv --system-site-packages "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/detector/requirements.txt"
bash "$ROOT/scripts/download_model.sh"

mkdir -p "$NODE_RED_DIR"
if [[ -f "$NODE_RED_DIR/settings.js" || -f "$NODE_RED_DIR/flows.json" ]]; then
    BACKUP="$NODE_RED_DIR/backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP"
    [[ -f "$NODE_RED_DIR/settings.js" ]] && cp -p "$NODE_RED_DIR/settings.js" "$BACKUP/settings.js"
    [[ -f "$NODE_RED_DIR/flows.json" ]] && cp -p "$NODE_RED_DIR/flows.json" "$BACKUP/flows.json"
    echo "Existing Node-RED settings backed up to $BACKUP"
fi
install -m 0644 "$ROOT/nodered/settings.js" "$NODE_RED_DIR/settings.js"
install -m 0644 "$ROOT/nodered/flows.json" "$NODE_RED_DIR/flows.json"
(cd "$NODE_RED_DIR" && npm install --no-save \
    "$ROOT/node-red-contrib-pi-camera-stream" \
    "$ROOT/node-red-contrib-pi-object-detector")

sudo usermod -aG video "$USER" || true
sudo systemctl enable nodered.service
sudo systemctl restart nodered.service

echo "Node-RED installation complete. Check: systemctl status nodered.service"
echo "If this SSH session predates the video-group change, reconnect before camera testing."
