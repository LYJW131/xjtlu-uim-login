#!/usr/bin/env node
/**
 * 在 jsdom 里执行 UIM 瑞数 412 脚本（hook XHR、附加 KgdICDMu），
 * 再调用官方 JSON doLogin，把 TGC 写到 stdout。
 *
 * stdin:  { "username": "...", "password": "...", "otp": "123456" }
 * stdout: { "ok": true, "tgc": "...", "cookies": [...] }
 * 日志走 stderr。
 */
"use strict";

const fs = require("fs");
const crypto = require("crypto");
const { JSDOM, CookieJar, VirtualConsole } = require("jsdom");

const UIM_ORIGIN = "https://uim.xjtlu.edu.cn";
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

function log(...args) {
  console.error("[jsdom]", ...args);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function xhr(window, method, url, body, contentType) {
  return new Promise((resolve) => {
    const req = new window.XMLHttpRequest();
    req.open(method, url);
    req.setRequestHeader("Accept", "application/json, text/plain, */*");
    if (contentType) req.setRequestHeader("Content-Type", contentType);
    req.onload = () =>
      resolve({
        status: req.status,
        url: req.responseURL,
        text: String(req.responseText || ""),
      });
    req.onerror = () => resolve({ error: true, status: req.status, text: "" });
    req.send(body == null ? null : body);
  });
}

function encryptPassword(password, publicKey) {
  const pem = `-----BEGIN PUBLIC KEY-----\n${publicKey}\n-----END PUBLIC KEY-----`;
  return crypto
    .publicEncrypt(
      { key: pem, padding: crypto.constants.RSA_PKCS1_PADDING },
      Buffer.from(password),
    )
    .toString("base64");
}

function dumpCookies(jar) {
  return new Promise((resolve, reject) => {
    jar.store.getAllCookies((err, list) => {
      if (err) return reject(err);
      resolve(
        (list || []).map((item) => ({
          name: item.key,
          value: item.value,
          domain: item.domain,
          path: item.path || "/",
        })),
      );
    });
  });
}

async function waitPolicy(window) {
  let last = null;
  for (let i = 0; i < 25; i++) {
    last = await xhr(window, "GET", "/esc-sso/api/v3/auth/policy");
    if (last.status === 200 && last.text.includes("publicKey")) {
      return JSON.parse(last.text);
    }
    await sleep(400);
  }
  throw new Error(
    `瑞数挑战未完成或 policy 不可用: status=${last && last.status} body=${(last && last.text.slice(0, 120)) || ""}`,
  );
}

async function login(window, username, password, otp) {
  const policy = await waitPolicy(window);
  const param = (policy.data && policy.data.param) || {};
  if (!param.publicKey || !param.publicKeyId) {
    throw new Error("policy 响应缺少公钥");
  }

  let result = JSON.parse(
    (
      await xhr(
        window,
        "POST",
        "/esc-sso/api/v3/auth/doLogin",
        JSON.stringify({
          authType: "webLocalAuth",
          dataField: {
            username,
            password: encryptPassword(password, param.publicKey),
            publicKeyId: param.publicKeyId,
          },
        }),
        "application/json",
      )
    ).text,
  );
  log("doLogin", result.code, result.msg);

  const redirect = (result.data && result.data.redirect) || "";
  if (String(redirect).includes("mfaLogin") || String(result.code) !== "0") {
    if (!otp) throw new Error("需要 OTP 但未提供");
    result = JSON.parse(
      (
        await xhr(
          window,
          "POST",
          "/esc-sso/api/v3/auth/doLogin",
          JSON.stringify({
            authType: "webOtpAuth",
            dataField: { username, password: "", otp },
            redirectUri: "",
          }),
          "application/json",
        )
      ).text,
    );
    log("otp", result.code, result.msg);
  }

  if (String(result.code) !== "0") {
    throw new Error(`UIM 登录失败: ${result.code} ${result.msg || ""}`);
  }
}

async function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8") || "{}");
  if (!input.username || !input.password) {
    throw new Error("缺少 username/password");
  }

  const jar = new CookieJar();
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", () => {});

  log("loading UIM (瑞数 JS 挑战)");
  const dom = await JSDOM.fromURL(UIM_ORIGIN + "/", {
    userAgent: UA,
    cookieJar: jar,
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole,
  });
  await sleep(1500);

  await login(dom.window, input.username, input.password, input.otp);

  const cookies = await dumpCookies(jar);
  const tgc = (cookies.find((c) => c.name === "TGC") || {}).value || null;
  if (!tgc) throw new Error("登录成功但未拿到 TGC");

  process.stdout.write(JSON.stringify({ ok: true, tgc, cookies }));
}

main().catch((err) => {
  process.stdout.write(
    JSON.stringify({ ok: false, error: String(err && err.message ? err.message : err) }),
  );
  process.exitCode = 1;
});
