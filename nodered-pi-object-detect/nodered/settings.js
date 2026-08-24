"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const projectRoot = process.env.PI_OBJECT_DETECT_ROOT || "/home/mriki/nodered-pi-object-detect";
const credentialSecretPath = path.join(__dirname, "credential.secret");

function loadCredentialSecret() {
    if (process.env.NODE_RED_CREDENTIAL_SECRET) return process.env.NODE_RED_CREDENTIAL_SECRET;
    try {
        return fs.readFileSync(credentialSecretPath, "utf8").trim();
    } catch (_error) {
        const secret = crypto.randomBytes(32).toString("hex");
        fs.writeFileSync(credentialSecretPath, `${secret}\n`, { mode: 0o600 });
        return secret;
    }
}

module.exports = {
    uiPort: process.env.PORT || 1880,
    httpAdminRoot: "/red",
    httpNodeRoot: "/api",
    httpStatic: [{ path: path.join(projectRoot, "public"), root: "/" }],
    flowFile: "flows.json",
    credentialSecret: loadCredentialSecret(),
    editorTheme: {
        projects: { enabled: false }
    },
    logging: {
        console: { level: "info", metrics: false, audit: false }
    }
};
