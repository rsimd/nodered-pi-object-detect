"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

const PACKET_FRAME = 1;
const PACKET_STATUS = 2;
const PACKET_ERROR = 3;
const HEADER_BYTES = 5;
const MAX_PACKET_BYTES = 5 * 1024 * 1024;

module.exports = function register(RED) {
    function PiCameraStream(config) {
        RED.nodes.createNode(this, config);
        const node = this;
        const root = config.projectRoot || process.env.PI_OBJECT_DETECT_ROOT || "/home/mriki/nodered-pi-object-detect";
        const python = config.pythonPath || path.join(root, ".venv", "bin", "python");
        const pythonCommand = fs.existsSync(python) ? python : "python3";
        const workerConfig = path.join(root, config.configPath || "config/detector.json");
        let child = null;
        let packetBuffer = Buffer.alloc(0);
        let restartTimer = null;
        let closing = false;

        function sendStatus(payload) {
            node.send([null, { topic: "カメラ状態", payload }]);
        }

        function sendError(payload) {
            node.status({ fill: "red", shape: "dot", text: "エラー" });
            sendStatus({ state: "error", ...payload });
        }

        function handlePacket(packetType, payload) {
            if (packetType === PACKET_FRAME) {
                node.send([
                    {
                        topic: "カメラ映像",
                        payload,
                        contentType: "image/jpeg",
                        frame: { format: "jpeg", timestamp: new Date().toISOString() }
                    },
                    null
                ]);
                return;
            }
            let message;
            try {
                message = JSON.parse(payload.toString("utf8"));
            } catch (_error) {
                sendError({ last_error: "カメラノードの状態メッセージを解析できません" });
                return;
            }
            if (packetType === PACKET_STATUS) {
                const state = message.state || "不明";
                node.status({
                    fill: state === "running" ? "green" : "red",
                    shape: "dot",
                    text: state === "running" ? "映像取得中" : state
                });
                sendStatus(message);
            } else if (packetType === PACKET_ERROR) {
                sendError(message);
            }
        }

        function parsePackets(chunk) {
            packetBuffer = Buffer.concat([packetBuffer, chunk]);
            while (packetBuffer.length >= HEADER_BYTES) {
                const packetType = packetBuffer.readUInt8(0);
                const packetLength = packetBuffer.readUInt32BE(1);
                if (packetLength > MAX_PACKET_BYTES) {
                    sendError({ last_error: `カメラパケットが大きすぎます: ${packetLength} bytes` });
                    packetBuffer = Buffer.alloc(0);
                    return;
                }
                if (packetBuffer.length < HEADER_BYTES + packetLength) return;
                const payload = Buffer.from(packetBuffer.subarray(HEADER_BYTES, HEADER_BYTES + packetLength));
                packetBuffer = packetBuffer.subarray(HEADER_BYTES + packetLength);
                handlePacket(packetType, payload);
            }
        }

        function start() {
            if (child || closing) return;
            node.status({ fill: "yellow", shape: "ring", text: "起動中" });
            packetBuffer = Buffer.alloc(0);
            const processRef = childProcess.spawn(
                pythonCommand,
                ["-u", "-m", "detector.camera_stream_worker", "--root", root, "--config", workerConfig],
                { cwd: root, stdio: ["ignore", "pipe", "pipe"] }
            );
            child = processRef;
            processRef.stdout.on("data", parsePackets);
            processRef.stderr.setEncoding("utf8");
            processRef.stderr.on("data", (chunk) => {
                const error = chunk.trim();
                if (error) sendError({ last_error: error });
            });
            processRef.on("error", (error) => {
                sendError({ last_error: error.message });
            });
            processRef.on("exit", (code, signal) => {
                if (child === processRef) child = null;
                if (closing || processRef.intentionalStop) return;
                node.status({ fill: "red", shape: "ring", text: `停止 ${code ?? signal}` });
                sendError({ exit_code: code, signal, last_error: `カメラワーカーが停止しました: ${code ?? signal}` });
                if (config.autoRestart !== false) restartTimer = setTimeout(start, 5000);
            });
        }

        function stop() {
            if (restartTimer) clearTimeout(restartTimer);
            restartTimer = null;
            if (child) {
                const processRef = child;
                processRef.intentionalStop = true;
                child = null;
                processRef.kill("SIGTERM");
            }
        }

        node.on("input", (message, sendMessage, done) => {
            const command = message.command || message.topic;
            if (command === "stop") stop();
            else if (command === "restart") { stop(); setTimeout(start, 100); }
            else start();
            if (done) done();
        });
        node.on("close", (done) => {
            closing = true;
            stop();
            done();
        });

        if (config.autoStart !== false) start();
    }

    RED.nodes.registerType("pi-camera-stream", PiCameraStream);
};
