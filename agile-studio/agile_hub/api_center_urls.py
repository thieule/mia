"""Chuẩn hóa URL API Center lưu trong DB (đôi khi thiếu scheme do phiên bản cũ hoặc response lỗi)."""


def normalize_http_url(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith(("http://", "https://")):
        return s
    return "http://" + s.lstrip("/")


def normalize_websocket_url(raw: str) -> str:
    """Browser WebSocket bắt buộc có ws:// hoặc wss://."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith(("ws://", "wss://")):
        return s
    if s.startswith("http://"):
        return "ws://" + s[len("http://") :]
    if s.startswith("https://"):
        return "wss://" + s[len("https://") :]
    return "ws://" + s.lstrip("/")


def normalize_api_center_endpoints(ep: dict | None) -> dict:
    """Bổ sung scheme cho các endpoint trong JSON Hub."""
    if not isinstance(ep, dict):
        return {}
    out: dict = {}
    for k, v in ep.items():
        if v is None:
            continue
        sv = str(v).strip()
        if not sv:
            continue
        if k == "chat_ws":
            out[k] = normalize_websocket_url(sv)
        elif k in ("agents", "chat_dispatch", "agile_notifications_webhook"):
            out[k] = normalize_http_url(sv)
        else:
            out[k] = v
    return out
