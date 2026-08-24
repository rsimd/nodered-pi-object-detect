"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

module.exports = function register(RED) {
    function PiObjectDetector(config) {
        RED.nodes.createNode(this, config);
        const node = this;
        const root = config.projectRoot || process.env.PI_OBJECT_DETECT_ROOT || "/home/mriki/nodered-pi-object-detect";
        const python = config.pythonPath || path.join(root, ".venv", "bin", "python");
        const pythonCommand = fs.existsSync(python) ? python : "python3";
        const script = path.join(root, "detector", "worker.py");
        const workerConfig = path.join(root, config.configPath || "config/detector.json");
        let child = null;
        let buffer = "";
        let restartTimer = null;
        let closing = false;
        let pendingFrame = null;
        let workerReady = false;

        function send(port, topic, payload) {
            const message = { topic, payload };
            const outputs = [null, null, null];
            outputs[port] = message;
            node.send(outputs);
        }

        function start() {
            if (child || closing) return;
            node.status({ fill: "yellow", shape: "ring", text: "起動中" });
            const processRef = childProcess.spawn(
                pythonCommand,
                ["-u", "-m", "detector.worker", "--root", root, "--config", workerConfig, "--input-frames"],
                { cwd: root, stdio: ["pipe", "pipe", "pipe"] }
            );
            child = processRef;
            pendingFrame = null;
            workerReady = false;
            processRef.stdout.setEncoding("utf8");
            processRef.stdout.on("data", (chunk) => {
                buffer += chunk;
                const lines = buffer.split("\n");
                buffer = lines.pop();
                lines.forEach(handleLine);
            });
            processRef.stderr.setEncoding("utf8");
            processRef.stderr.on("data", (chunk) => {
                const error = chunk.trim();
                if (error) {
                    node.warn(error);
                    send(2, "エラー", { state: "error", last_error: error });
                }
            });
            processRef.on("error", (error) => {
                node.status({ fill: "red", shape: "dot", text: "起動失敗" });
                send(2, "エラー", { state: "error", last_error: error.message });
            });
            processRef.on("exit", (code, signal) => {
                if (child === processRef) child = null;
                if (closing || processRef.intentionalStop) return;
                node.status({ fill: "red", shape: "ring", text: `停止 ${code ?? signal}` });
                send(2, "エラー", { state: "error", exit_code: code, signal });
                if (config.autoRestart !== false) {
                    restartTimer = setTimeout(start, 5000);
                }
            });
        }

        function pumpFrame() {
            if (!child || !workerReady || !pendingFrame) return;
            const frame = pendingFrame;
            pendingFrame = null;
            workerReady = false;
            const header = Buffer.alloc(4);
            header.writeUInt32BE(frame.length, 0);
            try {
                child.stdin.write(Buffer.concat([header, frame]));
            } catch (error) {
                send(2, "エラー", { state: "error", last_error: error.message });
            }
        }

        function handleLine(line) {
            if (!line.trim()) return;
            let message;
            try {
                message = JSON.parse(line);
            } catch (error) {
                node.warn(`ワーカーメッセージを解析できません: ${line}`);
                return;
            }
            if (message.type === "status") {
                const payload = message.payload || {};
                node.status({
                    fill: payload.state === "running" ? "green" : "red",
                    shape: "dot",
                    text: payload.state === "running" ? "稼働中" : (payload.state || "不明")
                });
                send(0, "状態", payload);
            } else if (message.type === "ready") {
                workerReady = true;
                pumpFrame();
            } else if (message.type === "event") {
                send(1, "新規物体", message.payload || {});
            } else if (message.type === "error") {
                node.status({ fill: "red", shape: "dot", text: "エラー" });
                send(2, "エラー", message.payload || {});
            }
        }

        function stop() {
            if (restartTimer) clearTimeout(restartTimer);
            restartTimer = null;
            if (child) {
                const processRef = child;
                processRef.intentionalStop = true;
                child = null;
                processRef.kill("SIGTERM");
                child = null;
            }
            pendingFrame = null;
            workerReady = false;
        }

        node.on("input", (message, sendMessage, done) => {
            if (Buffer.isBuffer(message.payload)) {
                pendingFrame = message.payload;
                pumpFrame();
                if (done) done();
                return;
            }
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

    RED.nodes.registerType("pi-object-detector", PiObjectDetector);
};
