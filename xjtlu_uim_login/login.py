"""XJTLU UIM 登录实现。"""

from __future__ import annotations

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

    idp: 可选，{"action": UIM SAML ACS, "data": {SAMLRequest, ...}}
         在同一次 jsdom 会话里 POST 到学校 IdP。
    """
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


def get_tgc() -> str:
    username, password, otp_url = credentials()
    result = login(username, password, otp_now(otp_url))
    tgc = result.get("tgc")
    if not tgc:
        raise RuntimeError("登录成功但未返回 TGC")
    return tgc
