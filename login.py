#!/usr/bin/env python3
"""XJTLU UIM 最小登录：jsdom 过瑞数后调用 doLogin，返回 TGC。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "uim_jsdom.js"


def load_project_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def _credentials() -> tuple[str, str, str]:
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


def _otp_now(otp_url: str) -> str:
    import pyotp

    secret = parse_qs(urlparse(otp_url).query).get("secret", [None])[0]
    if not secret:
        raise ValueError("OTP URL 中缺少 secret 参数")
    return pyotp.TOTP(secret).now()


def _node_bin() -> str:
    found = shutil.which("node")
    if not found:
        raise RuntimeError("未找到 node。请安装 Node.js 18+ 并加入 PATH")
    return found


def login(username: str, password: str, otp: str, timeout: int = 90) -> dict[str, Any]:
    """执行 UIM 登录，返回 {tgc, cookies}。"""
    if not SCRIPT.exists():
        raise RuntimeError(f"缺少 {SCRIPT.name}")
    if not (ROOT / "node_modules" / "jsdom").exists():
        raise RuntimeError("未安装 jsdom。请在项目根目录执行: npm install")

    env = os.environ.copy()
    env["NODE_PATH"] = str(ROOT / "node_modules") + os.pathsep + env.get("NODE_PATH", "")
    payload = {"username": username, "password": password, "otp": otp}
    proc = subprocess.run(
        [_node_bin(), str(SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
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
    username, password, otp_url = _credentials()
    result = login(username, password, _otp_now(otp_url))
    tgc = result.get("tgc")
    if not tgc:
        raise RuntimeError("登录成功但未返回 TGC")
    return tgc


if __name__ == "__main__":
    print(get_tgc())
