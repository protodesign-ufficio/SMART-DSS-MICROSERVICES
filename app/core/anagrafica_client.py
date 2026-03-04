import requests
from fastapi import HTTPException
from app.core.config import ANAGRAFICA_SERVICE_URL, ENABLE_ANAGRAFICA_DELEGATION


class AnagraficaDelegationError(Exception):
    pass


def delegation_enabled() -> bool:
    return ENABLE_ANAGRAFICA_DELEGATION


def _request_json(method: str, path: str, payload=None, timeout: float = 3.0):
    url = f"{ANAGRAFICA_SERVICE_URL.rstrip('/')}{path}"
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise AnagraficaDelegationError(str(exc)) from exc

    if response.status_code >= 400:
        detail = f"HTTP {response.status_code}"
        try:
            error_body = response.json()
            if isinstance(error_body, dict) and "detail" in error_body:
                detail = error_body["detail"]
            elif error_body:
                detail = str(error_body)
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)

    if not response.content:
        return None

    try:
        return response.json()
    except Exception as exc:
        raise AnagraficaDelegationError(str(exc)) from exc


def get_json(path: str, timeout: float = 3.0):
    return _request_json("GET", path, payload=None, timeout=timeout)


def post_json(path: str, payload, timeout: float = 3.0):
    return _request_json("POST", path, payload=payload, timeout=timeout)
