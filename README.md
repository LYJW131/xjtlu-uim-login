# XJTLU UIM Login

XJTLU 统一身份认证（UIM）最小登录：拿到 `TGC`，可选在同一会话里把 SAMLRequest POST 到学校 IdP（给 OWA 用）。

当前这版瑞数对常见浏览器 User-Agent 下发 412 挑战页，对 jsdom 的 User-Agent **直接 302、不跑挑战脚本**。因此默认路径是纯 Python `requests`，不启动 Chrome、不执行瑞数 JS。若探测到 412 / `$_ss`，再回退 Node jsdom。

```bash
pip install git+https://github.com/LYJW131/xjtlu-uim-login.git
```

HTTP 路径只需 Python。jsdom 回退才需要本机 Node.js 18+（首次会自动 `npm install`）。

## 发现：jsdom User-Agent 跳过 412

这不是把瑞数虚拟机纯算出来。对照实验表明，**同一条请求只改 `User-Agent`，结果就从 412 变成 302**。

观察到的 WAF（约 2026-07 之后的 UIM）：

- 挑战页 HTML 里是 `$_ss.nsd` / `$_ss.cd`（不是开源 rs-reverse 吃的 `$_ts`）
- `<meta r='m'>`
- 静态脚本 `/6UNV9eHTCoxa/Lnbr3ymf8Ycb.1058d2a.js`（Last-Modified: 2026-07-16）
- Cookie 名以 `P` 结尾，例如 `Gduw4tiSxoU8P`
- 浏览器登录页还会打 `/sso-mfa/rest/ueba/send`；JSON `doLogin` **不需要** UEBA

同一台机器、不带业务 Cookie、`GET https://uim.xjtlu.edu.cn/`（`allow_redirects=False`）：

| User-Agent | 结果 |
| --- | --- |
| Chrome 桌面 UA（以及 `curl_cffi` 伪装 Chrome TLS + 同一 UA） | **412**，正文是瑞数挑战 HTML |
| `Mozilla/5.0 (darwin) AppleWebKit/537.36 (KHTML, like Gecko) jsdom/30.0.1` | **302** → `/selfcare/` |

后续用同一个 jsdom UA：

1. `GET /esc-sso/api/v3/auth/policy` → JSON，含 RSA `publicKey` / `publicKeyId`
2. `POST /esc-sso/api/v3/auth/doLogin`，`authType=webLocalAuth`，密码 PKCS#1 v1.5 加密
3. 若返回 `mfaLogin`，再 `webOtpAuth`
4. 响应 Set-Cookie `TGC`（JWT）

jsdom 30 的 `fromURL` 默认就带上面那条 UA。之前以为必须执行挑战脚本才能过网关，实际上 **Gateway 按 UA 分流：浏览器 UA 才下发 VMP，jsdom UA 直接放行**。所以默认实现只复用这条 UA，用 `requests` 走官方 JSON API。

`login()` 先走 HTTP；若首页或 policy 仍是 412 / `$_ss`，再跑 `uim_jsdom.js`。学校若把该 UA 也纳入挑战，HTTP 路径会自己失败并回退。

试过、对**这一版**没用的：

- Playwright Chromium：412，随后 POST 400
- Playwright Firefox：GET/policy 200，POST 400
- `curl_cffi` TLS impersonate Chrome：仍 412（TLS 指纹不是开关）
- [rs-reverse](https://github.com/Sjj1024/rs-reverse) 1.16.3：只处理 `$_ts`；这版是 `$_ss`。跳过 allowlist 后 `_$ki is not a function`
- sdenv：Node 26 编 native 失败

没有把 XJTLU 适配进上述纯算工具。本仓库的「纯 Python」= 借用未被挑战的 UA，不是还原 opcode。

## 本地使用

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # 填账号
python3 login.py
```

成功时 stderr/stdout 会看到 `[http] doLogin 0 success` 和 `[+] HTTP 登录成功（未执行瑞数 JS）`，最后打印 TGC。

| 变量 | 说明 |
| --- | --- |
| `XJTLU_USERNAME` | UIM 用户名（不含邮箱后缀） |
| `XJTLU_PASSWORD` | 登录密码 |
| `XJTLU_OTP_URL` | `otpauth://` TOTP 地址 |

`credentials()` 会从当前工作目录向上找 `.env`，以及本仓库根目录的 `.env`。只设了 shell 环境变量也可以，不必有文件。

## 作为库

```python
from xjtlu_uim_login import get_tgc, login, credentials, otp_now

tgc = get_tgc()

user, password, otp_url = credentials()
result = login(user, password, otp_now(otp_url))
print(result["tgc"], [c["name"] for c in result["cookies"]])

# 可选：同一会话里把 SAMLRequest POST 到学校 IdP（给 OWA 用）
# result = login(..., idp={"action": "...", "data": {...}})
# result["samlHtml"]
```

本项目仅用于个人账号自动化，请遵守学校规定。
