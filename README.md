# XJTLU UIM Login

XJTLU 统一身份认证（UIM）最小登录。用 Node.js **jsdom** 执行瑞数 412 脚本后调用官方 `doLogin`，返回 `TGC`。不启动 Chrome。

可作为 Python 包被其它项目引用：

```bash
pip install git+https://github.com/LYJW131/xjtlu-uim-login.git
```

首次登录会在包目录自动 `npm install jsdom`（需要本机 Node.js 18+）。

## 本地使用

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # 填账号
python3 login.py
```

| 变量 | 说明 |
| --- | --- |
| `XJTLU_USERNAME` | UIM 用户名（不含邮箱后缀） |
| `XJTLU_PASSWORD` | 登录密码 |
| `XJTLU_OTP_URL` | `otpauth://` TOTP 地址 |

## 作为库

```python
from xjtlu_uim_login import get_tgc, login, credentials, otp_now

tgc = get_tgc()

user, password, otp_url = credentials()
result = login(user, password, otp_now(otp_url))
print(result["tgc"], [c["name"] for c in result["cookies"]])

# 可选：同一 jsdom 会话里把 SAMLRequest POST 到学校 IdP（给 OWA 用）
# result = login(..., idp={"action": "...", "data": {...}})
# result["samlHtml"]
```

本项目仅用于个人账号自动化，请遵守学校规定。
