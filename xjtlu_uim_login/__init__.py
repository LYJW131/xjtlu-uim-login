"""XJTLU UIM 登录：默认 HTTP（jsdom UA），412 时回退 jsdom。"""

from .login import credentials, get_tgc, load_project_env, login, otp_now

__all__ = ["credentials", "get_tgc", "load_project_env", "login", "otp_now"]
