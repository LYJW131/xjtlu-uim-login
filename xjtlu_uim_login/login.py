"""XJTLU UIM 登录实现。"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
SCRIPT = PACKAGE_DIR / "uim_jsdom.js"

UIM_ORIGIN = "https://uim.xjtlu.edu.cn"
POLICY_URL = f"{UIM_ORIGIN}/esc-sso/api/v3/auth/policy"
DOLOGIN_URL = f"{UIM_ORIGIN}/esc-sso/api/v3/auth/doLogin"
# 此版本瑞数对浏览器 UA 发 412，对 jsdom UA 直接 302，不跑挑战脚本
JSDOM_UA = "Mozilla/5.0 (darwin) AppleWebKit/537.36 (KHTML, like Gecko) jsdom/30.0.1"


class WafChallenge(RuntimeError):
    """收到 412 / $_ss 挑战页。"""


def load_project_env() -> None:
    """加载 .env：当前工作目录向上查找，以及登录仓库根目录。"""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)
    load_dotenv(REPO_DIR / ".env", override=False)


def credentials() -> tuple[str, str, str]:
    load_project_env()
    username = os.environ.get("XJTLU_USERNAME")
    password = os.environ.get("XJTLU_PASSWORD")
    otp_url = os.environ.get("XJTLU_OTP_URL")
    if not username:
        raise ValueError("环境变量 XJTLU_USERNAME 未设置")
    if not password:
        raise ValueError("环境变量 XJTLU_PASSWORD 未设置")
    if not otp_url:
        raise ValueError("环境变量 XJTLU_OTP_URL 未设置")
    return username, password, otp_url


def otp_now(otp_url: str | None = None) -> str:
    import pyotp

    if otp_url is None:
        _, _, otp_url = credentials()
    secret = parse_qs(urlparse(otp_url).query).get("secret", [None])[0]
    if not secret:
        raise ValueError("OTP URL 中缺少 secret 参数")
    return pyotp.TOTP(secret).now()


def _node_bin() -> str:
    found = shutil.which("node")
    if not found:
        raise RuntimeError("未找到 node。请安装 Node.js 18+ 并加入 PATH")
    return found


def _encrypt_password(password: str, public_key: str) -> str:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----"
    key = serialization.load_pem_public_key(pem.encode(), backend=default_backend())
    return base64.b64encode(key.encrypt(password.encode(), padding.PKCS1v15())).decode()


def _dump_cookies(session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cookie in session.cookies:
        out.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path or "/",
            }
        )
    return out


def _looks_like_challenge(resp) -> bool:
    if resp.status_code == 412:
        return True
    text = resp.text[:800] if resp.text else ""
    return "$_ss" in text or "$_ts" in text


def _login_http(
    username: str,
    password: str,
    otp: str | None,
    *,
    idp: dict[str, Any] | None,
    cookies: list[dict[str, Any]] | None,
    skip_login: bool,
    timeout: int,
) -> dict[str, Any]:
    import requests

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": JSDOM_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en",
        }
    )
    for item in cookies or []:
        session.cookies.set(
            item["name"],
            item["value"],
            domain=item.get("domain") or "uim.xjtlu.edu.cn",
            path=item.get("path") or "/",
        )

    probe = session.get(UIM_ORIGIN + "/", timeout=timeout, allow_redirects=False)
    if _looks_like_challenge(probe):
        raise WafChallenge("HTTP 412 / 瑞数挑战页")

    if not skip_login:
        policy_resp = session.get(POLICY_URL, timeout=timeout)
        if _looks_like_challenge(policy_resp):
            raise WafChallenge("policy 被挑战")
        policy = policy_resp.json()
        param = (policy.get("data") or {}).get("param") or {}
        if not param.get("publicKey") or not param.get("publicKeyId"):
            raise RuntimeError("policy 响应缺少公钥")
        result = session.post(
            DOLOGIN_URL,
            json={
                "authType": "webLocalAuth",
                "dataField": {
                    "username": username,
                    "password": _encrypt_password(password, param["publicKey"]),
                    "publicKeyId": param["publicKeyId"],
                },
            },
            timeout=timeout,
        ).json()
        print("[http]", "doLogin", result.get("code"), result.get("msg"))
        data = result.get("data") or {}
        redirect = data.get("redirect") if isinstance(data, dict) else str(data)
        if "mfaLogin" in str(redirect) or str(result.get("code")) != "0":
            if not otp:
                raise RuntimeError("需要 OTP 但未提供")
            result = session.post(
                DOLOGIN_URL,
                json={
                    "authType": "webOtpAuth",
                    "dataField": {"username": username, "password": "", "otp": otp},
                    "redirectUri": "",
                },
                timeout=timeout,
            ).json()
            print("[http]", "otp", result.get("code"), result.get("msg"))
        if str(result.get("code")) != "0":
            raise RuntimeError(f"UIM 登录失败: {result.get('code')} {result.get('msg') or ''}")

    saml_html = None
    if idp and idp.get("action") and idp.get("data"):
        resp = session.post(idp["action"], data=idp["data"], timeout=timeout)
        if resp.status_code != 200 or "SAMLResponse" not in resp.text:
            raise RuntimeError(f"IdP SAML 失败: status={resp.status_code}")
        print("[http]", "idp", resp.status_code, "len", len(resp.text))
        saml_html = resp.text

    tgc = session.cookies.get("TGC")
    if not tgc and not skip_login:
        raise RuntimeError("登录成功但未拿到 TGC")
    out: dict[str, Any] = {"ok": True, "tgc": tgc, "cookies": _dump_cookies(session)}
    if saml_html is not None:
        out["samlHtml"] = saml_html
    return out


def _ensure_jsdom() -> None:
    if (PACKAGE_DIR / "node_modules" / "jsdom").exists():
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，无法安装 jsdom")
    pkg = PACKAGE_DIR / "package.json"
    if not pkg.exists():
        raise RuntimeError(f"缺少 {pkg}")
    print("[*] 首次使用，正在 package 目录执行 npm install")
    subprocess.run([npm, "install"], cwd=str(PACKAGE_DIR), check=True)


def _login_jsdom(
    username: str,
    password: str,
    otp: str | None,
    *,
    idp: dict[str, Any] | None,
    cookies: list[dict[str, Any]] | None,
    skip_login: bool,
    timeout: int,
) -> dict[str, Any]:
    if not SCRIPT.exists():
        raise RuntimeError(f"缺少 {SCRIPT.name}")
    _ensure_jsdom()

    env = os.environ.copy()
    env["NODE_PATH"] = str(PACKAGE_DIR / "node_modules") + os.pathsep + env.get("NODE_PATH", "")
    payload: dict[str, Any] = {
        "username": username,
        "password": password,
        "otp": otp,
        "skipLogin": skip_login,
    }
    if idp:
        payload["idp"] = idp
    if cookies:
        payload["cookies"] = cookies

    proc = subprocess.run(
        [_node_bin(), str(SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PACKAGE_DIR),
        timeout=timeout,
        check=False,
    )
    if proc.stderr:
        for line in proc.stderr.strip().splitlines():
            print(line)
    if not proc.stdout.strip():
        raise RuntimeError(f"jsdom 无输出, exit={proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"jsdom 输出不是 JSON: {proc.stdout[:300]}") from exc
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "jsdom 登录失败")
    return data


def login(
    username: str,
    password: str,
    otp: str | None = None,
    *,
    idp: dict[str, Any] | None = None,
    cookies: list[dict[str, Any]] | None = None,
    skip_login: bool = False,
    timeout: int = 90,
) -> dict[str, Any]:
    """
    执行 UIM 登录，返回 {tgc, cookies, samlHtml?}。

    当前瑞数版本对 jsdom UA 不发 412，优先纯 HTTP；若仍拿到挑战页则回退 jsdom。
    """
    try:
        result = _login_http(
            username,
            password,
            otp,
            idp=idp,
            cookies=cookies,
            skip_login=skip_login,
            timeout=timeout,
        )
        print("[+] HTTP 登录成功（未执行瑞数 JS）")
        return result
    except WafChallenge as exc:
        print(f"[*] {exc}，回退 jsdom")
    return _login_jsdom(
        username,
        password,
        otp,
        idp=idp,
        cookies=cookies,
        skip_login=skip_login,
        timeout=timeout,
    )


def get_tgc() -> str:
    username, password, otp_url = credentials()
    result = login(username, password, otp_now(otp_url))
    tgc = result.get("tgc")
    if not tgc:
        raise RuntimeError("登录成功但未返回 TGC")
    return tgc
