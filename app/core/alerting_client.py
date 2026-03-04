import requests
from fastapi import HTTPException
from app.core.config import ALERTING_SERVICE_URL, ENABLE_ALERTING_DELEGATION


class AlertingDelegationError(Exception):
    pass


def delegation_enabled() -> bool:
    return ENABLE_ALERTING_DELEGATION


def _request_json(method: str, path: str, payload=None, timeout: float = 4.0):
    url = f"{ALERTING_SERVICE_URL.rstrip('/')}{path}"
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise AlertingDelegationError(str(exc)) from exc

    if response.status_code >= 400:
        detail = f"HTTP {response.status_code}"
        try:
            body = response.json()
            if isinstance(body, dict) and "detail" in body:
                detail = body["detail"]
            elif body:
                detail = str(body)
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)

    if not response.content:
        return None

    try:
        return response.json()
    except Exception as exc:
        raise AlertingDelegationError(str(exc)) from exc


def get_json(path: str, timeout: float = 4.0):
    return _request_json("GET", path, payload=None, timeout=timeout)
