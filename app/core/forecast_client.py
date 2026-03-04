import requests
from fastapi import HTTPException
from app.core.config import FORECAST_SERVICE_URL, ENABLE_FORECAST_DELEGATION


class ForecastDelegationError(Exception):
    pass


def delegation_enabled() -> bool:
    return ENABLE_FORECAST_DELEGATION


def _request_json(method: str, path: str, payload=None, timeout: float = 8.0):
    url = f"{FORECAST_SERVICE_URL.rstrip('/')}{path}"
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise ForecastDelegationError(str(exc)) from exc

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
        raise ForecastDelegationError(str(exc)) from exc


def post_json(path: str, payload, timeout: float = 8.0):
    return _request_json("POST", path, payload=payload, timeout=timeout)
