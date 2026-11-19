import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode
from app import hiu
from app.config import settings
from app.models import User

STEP_SECONDS, DIGITS, WINDOW = 30, 6, 1 
def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")

def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)

def code_at(secret: str, timestamp: float) -> str:
    return _code(secret, int(timestamp // STEP_SECONDS))

def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    code = "".join(code.split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(_code(secret, step), code):
            return step
    return None

def provisioning_uri(user: User, secret: str) -> str:
    label = quote(f"{settings.mfa_issuer}:{user.username}")
    query = urlencode({"secret": secret, "issuer": settings.mfa_issuer, "digits": DIGITS, "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"

def secret_of(user: User) -> str | None:
    return hiu.unseal(user.mfa_secret) if user.mfa_secret else None

def store_secret(user: User, secret: str) -> None:
    user.mfa_secret = hiu.seal(secret)
    user.mfa_enabled = False
    user.mfa_last_step = None

def clear(user: User) -> None:
    user.mfa_secret, user.mfa_enabled, user.mfa_last_step = None, False, None

def verify(user: User, code: str | None) -> bool:
    secret = secret_of(user)
    if not secret or not code:
        return False
    step = matching_step(secret, code)
    if step is None or (user.mfa_last_step is not None and step <= user.mfa_last_step):
        return False
    user.mfa_last_step = step
    return True
