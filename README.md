# XJTLU UIM Login

XJTLU 统一身份认证（UIM）最小登录：拿到 `TGC`，可选在同一会话里把 SAMLRequest POST 到学校 IdP（给 OWA 用）。

当前这版瑞数**默认给 412 挑战页**，但对手机 WebKit / 若干原生 HTTP 客户端子串直接 302、不跑挑战脚本。默认路径因此是纯 Python `requests`（实现里复用 jsdom 在 macOS 上的默认 UA，因为里面有 `darwin`）。若探测到 412 / `$_ss`，再回退 Node jsdom。

```bash
pip install git+https://github.com/LYJW131/xjtlu-uim-login.git
```

HTTP 路径只需 Python。jsdom 回退才需要本机 Node.js 18+（首次会自动 `npm install`）。

## 发现：按 UA 分流，不是纯算 VM

这不是把瑞数虚拟机还原出来。对照实验：同一台机器、不带业务 Cookie、只改 `User-Agent` 去 `GET https://uim.xjtlu.edu.cn/`（`allow_redirects=False`），结果在 **412 挑战页** 和 **302 `/selfcare/`** 之间切换。约 200 条 UA。

### 这版 WAF

约 2026-07 之后的 UIM：

- 挑战页 HTML 是 `$_ss.nsd` / `$_ss.cd`（不是开源 rs-reverse 吃的 `$_ts`）
- `<meta r='m'>`
- 静态脚本 `/6UNV9eHTCoxa/Lnbr3ymf8Ycb.1058d2a.js`（Last-Modified: 2026-07-16）
- Cookie 名以 `P` 结尾，例如 `Gduw4tiSxoU8P`
- 浏览器登录页还会打 `/sso-mfa/rest/ueba/send`；JSON `doLogin` **不需要** UEBA

`curl_cffi` 伪装 Chrome TLS + Chrome UA 仍是 412，所以开关是 UA，不是 TLS 指纹。

### 结论

**默认 412。** 空 UA、curl、requests、Go、Java、Node、Postman、桌面 Chrome / Firefox / Safari / Edge / IE、HeadlessChrome、Playwright、Selenium、爬虫 UA 都走挑战。

放行只有两类（大小写不敏感）：

1. **子串命中就过**（不是单词边界）。下面这些字符串单独出现即 302：

   | 子串 | 典型来源 |
   | --- | --- |
   | `darwin` | macOS 上 jsdom 的 `(darwin)`；也匹配 `CFNetwork … Darwin/23` |
   | `okhttp` | Android 原生 HTTP |
   | `dalvik` | Android 运行时 |
   | `cfnetwork` | iOS / macOS 原生 |
   | `arkweb` | 鸿蒙 WebView |

   因此 `darwin`、`xxdarwinxx`、`not-a-darwin-thing`、`curl/8.7.1 darwin`、`python-requests/2.32.3 (darwin)` 都会过。`darwi` / `arwin` 差一个字母则 412。

2. **像手机 WebKit**：设备词和 `AppleWebKit` 必须同时有。

   | 过（302） | 不过（412） |
   | --- | --- |
   | iPhone / iPad / iPod + AppleWebKit（Safari、CriOS、手机微信 / QQ） | 只有 `Mozilla/5.0 (iPhone)` |
   | `Android` + AppleWebKit（Chrome、微信、华为、三星、Kindle Silk） | 只有 `Android` / `Mobile` |
   | OpenHarmony + AppleWebKit | Firefox Android（Gecko，无 AppleWebKit） |
   | 最短 Android：`Mozilla/5.0 (android) AppleWebKit/537.36` | Opera Mini（Presto） |
   | 最短 iOS：`Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15` | 桌面微信 / Mac 微信、iPad 桌面模式（Macintosh Safari） |
   | | ChromeOS、PlayStation、Xbox、BlackBerry |

jsdom **本身不在白名单里**。`jsdom/30.0.1` 单独是 412。macOS 上 jsdom 30 的 `fromURL` 默认 UA 带 `(darwin)`，误撞第 1 类。Linux / Windows 上的 jsdom 是 `(linux)` / `(win32)`，实测 412。实现里把 darwin 这条 UA 写死，所以从哪台机器发 HTTP 都能走同一条放行规则。

`okhttp/4.12.0`、`Dalvik`、`darwin`、完整 iPhone / Android UA、以及上述 jsdom UA，随后 `GET /esc-sso/api/v3/auth/policy` 都能拿到 `publicKey`。WAF 放行后走同一套官方 JSON API。

登录步骤（HTTP 路径）：

1. `GET /esc-sso/api/v3/auth/policy` → JSON，含 RSA `publicKey` / `publicKeyId`
2. `POST /esc-sso/api/v3/auth/doLogin`，`authType=webLocalAuth`，密码 PKCS#1 v1.5 加密
3. 若返回 `mfaLogin`，再 `webOtpAuth`
4. 响应 Set-Cookie `TGC`（JWT）

`login()` 先走 HTTP；若首页或 policy 仍是 412 / `$_ss`，再跑 `uim_jsdom.js`。学校若把这些子串和手机 WebKit 也纳入挑战，HTTP 路径会失败并回退。

### 试过、对这一版没用的

- Playwright Chromium：412，随后 POST 400
- Playwright Firefox：GET/policy 200，POST 400
- `curl_cffi` TLS impersonate Chrome：仍 412
- [rs-reverse](https://github.com/Sjj1024/rs-reverse) 1.16.3：只处理 `$_ts`；这版是 `$_ss`。跳过 allowlist 后 `_$ki is not a function`
- sdenv：Node 26 编 native 失败

没有把 XJTLU 适配进上述纯算工具。本仓库的「纯 Python」= 借用当前未被挑战的 UA，不是还原 opcode。

## 本地使用

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # 填账号
python3 login.py
```

成功时会看到 `[http] doLogin 0 success` 和 `[+] HTTP 登录成功（未执行瑞数 JS）`，最后打印 TGC。

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
