# XJTLU UIM Login

XJTLU 统一身份认证（UIM）最小登录实现。过瑞数 412 JS 挑战后调用官方 `doLogin`，返回 `TGC`。

不启动 Chrome / Playwright。用 Node.js **jsdom** 执行页面下发的挑战脚本（hook `XMLHttpRequest`、附加一次性参数 `KgdICDMu`），再走：

1. `GET /esc-sso/api/v3/auth/policy` → RSA 公钥  
2. `POST /esc-sso/api/v3/auth/doLogin` `authType=webLocalAuth`  
3. 如需 MFA：`webOtpAuth`  
4. 从 cookie 取出 `TGC`

## 环境

- Python 3.12+
- Node.js 18+

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
cp .env.example .env
```

编辑 `.env`：

| 变量 | 说明 |
| --- | --- |
| `XJTLU_USERNAME` | UIM 用户名（不含邮箱后缀） |
| `XJTLU_PASSWORD` | 登录密码 |
| `XJTLU_OTP_URL` | `otpauth://` TOTP 地址 |

## 使用

```bash
python3 login.py
```

成功时 stdout 只有一行 TGC。瑞数相关日志在 stderr。

作为库：

```python
from login import get_tgc, login

tgc = get_tgc()

# 或拿到全部 cookie
from login import _credentials, _otp_now, login as uim_login
user, password, otp_url = _credentials()
result = uim_login(user, password, _otp_now(otp_url))
print(result["tgc"])
print([c["name"] for c in result["cookies"]])
```

## 文件

| 文件 | 职责 |
| --- | --- |
| `uim_jsdom.js` | jsdom 过瑞数 + `doLogin` |
| `login.py` | 读 `.env`、生成 OTP、调用 Node、打印 TGC |

本项目仅用于个人账号自动化，请遵守学校规定。
