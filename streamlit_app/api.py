"""Thin client for the ABDM Hospital FastAPI backend (Bearer token kept in this user's Streamlit session)."""
import os
from typing import Any

import requests
import streamlit as st

BASE_URL = os.environ.get("ABDM_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
TIMEOUT = 900  # HL7 validation and AI extraction can take minutes


class ApiError(Exception):
    def __init__(self, message: str, status: int, code: str | None = None, detail: Any = None):
        super().__init__(message)
        self.status, self.code, self.detail = status, code, detail


def _error(resp: requests.Response) -> ApiError:
    try:
        raw = resp.json().get("detail")
    except ValueError:
        raw = None
    detail, code = raw, None
    if isinstance(raw, dict):
        code = raw.get("code")
        detail = raw.get("message") or raw.get("detail")
        if raw.get("requirements"):
            detail = f"{detail or 'Not ready'}: " + "; ".join(raw["requirements"])
        if not detail and raw.get("duplicates") is not None:
            detail = "Possible duplicate patients found"
    elif isinstance(raw, list):  # FastAPI validation errors
        detail = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', [])[1:])}: {e.get('msg')}" for e in raw)
    return ApiError(str(detail or f"Request failed ({resp.status_code})"), resp.status_code, code, raw)


def _send(method: str, path: str, **kwargs) -> requests.Response:
    auth = st.session_state.get("auth")
    headers = {"Authorization": f"Bearer {auth['token']}"} if auth else {}
    try:
        resp = requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.ConnectionError:
        raise ApiError(f"Cannot reach the backend at {BASE_URL}. Is it running?", 0)
    if resp.status_code == 401 and auth and not path.startswith("/auth/"):
        # session ended (idle timeout, password change, sign-out elsewhere)
        st.session_state.auth = None
        st.session_state.signed_out_reason = "Your session ended. Please sign in again."
        st.rerun()
    if resp.status_code >= 400:
        raise _error(resp)
    return resp


def login(username: str, password: str, otp: str | None = None) -> dict:
    try:
        resp = requests.post(f"{BASE_URL}/auth/login", json={"username": username, "password": password, "otp": otp or None},
                             timeout=60)
    except requests.ConnectionError:
        raise ApiError(f"Cannot reach the backend at {BASE_URL}. Is it running?", 0)
    if resp.status_code != 200:
        raise _error(resp)
    return resp.json()


def call(method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
    resp = _send(method, path, params=params, json=json)
    return resp.json() if resp.content else None


def get(path: str, **params) -> Any:
    return call("GET", path, params={k: v for k, v in params.items() if v not in (None, "")})


def post(path: str, json: Any = None) -> Any:
    return call("POST", path, json=json)


def put(path: str, json: Any = None) -> Any:
    return call("PUT", path, json=json)


def patch(path: str, json: Any = None) -> Any:
    return call("PATCH", path, json=json)


def delete(path: str) -> Any:
    return call("DELETE", path)


def get_bytes(path: str) -> bytes:
    return _send("GET", path).content


def upload(path: str, file_name: str, data: bytes, content_type: str, fields: dict | None = None) -> Any:
    resp = _send("POST", path, files={"file": (file_name, data, content_type)},
                 data={k: str(v) for k, v in (fields or {}).items() if v is not None})
    return resp.json()


def refresh_user() -> None:
    """Reload the signed-in user (permissions, two-step status) after account changes."""
    st.session_state.auth["user"] = get("/auth/me")


def logout(everywhere: bool = False) -> None:
    try:
        call("POST", "/auth/logout-all" if everywhere else "/auth/logout")
    except ApiError:
        pass
    st.session_state.auth = None
