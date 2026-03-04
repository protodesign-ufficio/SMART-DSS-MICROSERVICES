import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE = "http://localhost:25080"
TIMEOUT = 45


def safe_request(method: str, url: str, json_body: Any = None, timeout: int = TIMEOUT):
    try:
        resp = requests.request(method, url, json=json_body, timeout=timeout)
        text = resp.text[:400]
        try:
            body = resp.json()
        except Exception:
            body = text
        return {
            "ok": True,
            "status": resp.status_code,
            "body": body,
            "url": url,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "body": str(exc),
            "url": url,
        }


def get_seed_data() -> Dict[str, Any]:
    seeds: Dict[str, Any] = {
        "today": datetime.date.today().isoformat(),
    }

    for name, path in [
        ("porti", "/porto/lista"),
        ("tratte", "/tratta/lista"),
        ("vascelli", "/vascello/lista"),
        ("corse", "/corsa/lista"),
        ("piani", "/piano/lista"),
    ]:
        r = safe_request("GET", BASE + path)
        if r["ok"] and r["status"] == 200 and isinstance(r["body"], list):
            seeds[name] = r["body"]
        else:
            seeds[name] = []

    # Try to materialize at least one percorso for reliable path-param tests
    corsa_id = None
    vascello_id = None
    if seeds["corse"]:
        corsa_id = seeds["corse"][0].get("id")
    if seeds["vascelli"]:
        vascello_id = seeds["vascelli"][0].get("id")

    if corsa_id and vascello_id:
        payload = {
            "items": [
                {
                    "corsa_id": corsa_id,
                    "vascello_id": vascello_id,
                    "eps_time": 5,
                    "fake_data": True,
                    "ve_min": 0.1,
                    "tolerance": 1,
                }
            ]
        }
        safe_request("POST", BASE + "/weather_routing/carico", json_body=payload, timeout=180)
        rp = safe_request(
            "GET",
            BASE + f"/percorso/by_corsa/{corsa_id}?order_by=created_at&mode=DESC&limit=5&vascello_id={vascello_id}",
        )
        if rp["ok"] and rp["status"] == 200 and isinstance(rp["body"], dict):
            perc = rp["body"].get("percorsi", [])
            seeds["percorsi"] = perc
        else:
            seeds["percorsi"] = []
    else:
        seeds["percorsi"] = []

    # Build common IDs
    seeds["porto_id"] = seeds["porti"][0].get("id") if seeds["porti"] else "00000000-0000-0000-0000-000000000001"
    seeds["porto_id_2"] = seeds["porti"][1].get("id") if len(seeds["porti"]) > 1 else seeds["porto_id"]
    seeds["tratta_id"] = seeds["tratte"][0].get("id") if seeds["tratte"] else "00000000-0000-0000-0000-000000000002"
    seeds["vascello_id"] = seeds["vascelli"][0].get("id") if seeds["vascelli"] else "00000000-0000-0000-0000-000000000003"
    seeds["mmsi"] = str(seeds["vascelli"][0].get("mmsi")) if seeds["vascelli"] and seeds["vascelli"][0].get("mmsi") else "123456789"
    seeds["corsa_id"] = seeds["corse"][0].get("id") if seeds["corse"] else "00000000-0000-0000-0000-000000000004"
    seeds["piano_id"] = seeds["piani"][0].get("id") if seeds["piani"] else "00000000-0000-0000-0000-000000000005"
    seeds["percorso_id"] = seeds["percorsi"][0].get("id") if seeds["percorsi"] else "00000000-0000-0000-0000-000000000006"

    # Try assegnazione id if possible
    seeds["assegnazione_id"] = "00000000-0000-0000-0000-000000000007"
    if seeds["piano_id"]:
        ra = safe_request("GET", BASE + f"/assegnazione/by_piano/{seeds['piano_id']}")
        if ra["ok"] and ra["status"] == 200 and isinstance(ra["body"], list) and ra["body"]:
            cand = ra["body"][0]
            if isinstance(cand, dict) and cand.get("id"):
                seeds["assegnazione_id"] = cand.get("id")

    return seeds


def substitute_path(path: str, seeds: Dict[str, Any]) -> str:
    mapping = {
        "porto_id": seeds["porto_id"],
        "tratta_id": seeds["tratta_id"],
        "vascello_id": seeds["vascello_id"],
        "mmsi": seeds["mmsi"],
        "corsa_id": seeds["corsa_id"],
        "piano_id": seeds["piano_id"],
        "percorso_id": seeds["percorso_id"],
        "assegnazione_id": seeds["assegnazione_id"],
        "nome": "TEST",
        "giorno": seeds["today"],
        "previsione_id": "00000000-0000-0000-0000-000000000008",
        "id": "00000000-0000-0000-0000-000000000009",
    }

    def repl(match):
        key = match.group(1)
        return str(mapping.get(key, f"sample-{key}"))

    return re.sub(r"\{([^}]+)\}", repl, path)


def build_query(path: str, method: str) -> str:
    if method != "GET":
        return ""
    if path.startswith("/corsa/giorno"):
        return f"?giorno={datetime.date.today().isoformat()}&solofuture=false"
    if path.startswith("/percorso/by_corsa/"):
        return "?order_by=tempo_percorrenza_min&mode=ASC&limit=10"
    if path.startswith("/allarme/lista"):
        return "?limit=100"
    return ""


def build_safe_body(path: str, seeds: Dict[str, Any]) -> Optional[dict]:
    # Safe valid payloads for key flows; for others return {} to trigger validation instead of data mutation
    if path == "/weather_routing/carico":
        return {
            "items": [
                {
                    "corsa_id": seeds["corsa_id"],
                    "vascello_id": seeds["vascello_id"],
                    "eps_time": 5,
                    "fake_data": True,
                    "ve_min": 0.1,
                    "tolerance": 1,
                }
            ]
        }
    if path == "/weather_routing/vuoto":
        return {
            "items": [
                {
                    "porto_partenza_id": seeds["porto_id"],
                    "porto_destinazione_id": seeds["porto_id_2"],
                    "datetime_partenza": datetime.datetime.now(datetime.UTC).isoformat(),
                    "vascello_id": seeds["vascello_id"],
                    "fake_data": True,
                    "ve_min": 0.1,
                    "tolerance": 1,
                }
            ]
        }
    if path.startswith("/corsa/") and path.endswith("/prevedi"):
        return {"note": "audit-safe"}

    # generic safe body (most mutation endpoints should return 4xx validation, still confirming handler wiring)
    return {}


def main():
    spec_r = safe_request("GET", BASE + "/openapi.json", timeout=90)
    if not spec_r["ok"] or spec_r["status"] != 200 or not isinstance(spec_r["body"], dict):
        raise RuntimeError("Cannot fetch OpenAPI from new stack")

    spec = spec_r["body"]
    paths = spec.get("paths", {})

    seeds = get_seed_data()

    results: List[Dict[str, Any]] = []

    for raw_path, ops in sorted(paths.items()):
        for method in sorted(ops.keys()):
            m = method.upper()
            resolved = substitute_path(raw_path, seeds)
            query = build_query(raw_path, m)
            url = BASE + resolved + query

            payload = None
            if m in {"POST", "PUT", "PATCH", "DELETE"}:
                payload = build_safe_body(raw_path, seeds)

            resp = safe_request(m, url, json_body=payload, timeout=180 if "weather_routing" in raw_path else TIMEOUT)
            results.append(
                {
                    "method": m,
                    "path": raw_path,
                    "url": url,
                    "status": resp["status"],
                    "ok": resp["ok"],
                    "payload_mode": "safe-body" if payload is not None else "no-body",
                    "body_preview": resp["body"] if isinstance(resp["body"], str) else None,
                }
            )

    total = len(results)
    by_status: Dict[str, int] = {}
    for r in results:
        key = str(r["status"])
        by_status[key] = by_status.get(key, 0) + 1

    hard_fail = [r for r in results if (r["status"] is None) or (isinstance(r["status"], int) and r["status"] >= 500)]

    md = []
    md.append("# Full Endpoint Audit (New Stack)")
    md.append("")
    md.append(f"Total operations tested: {total}")
    md.append(f"Status distribution: {json.dumps(by_status, ensure_ascii=False)}")
    md.append(f"Hard failures (5xx or no-response): {len(hard_fail)}")
    md.append("")
    md.append("## Hard failures")
    md.append("| Method | Path | Status | URL |")
    md.append("|---|---|---:|---|")
    for r in hard_fail:
        md.append(f"| {r['method']} | {r['path']} | {r['status']} | {r['url']} |")

    md.append("")
    md.append("## All results")
    md.append("| Method | Path | Status | Payload Mode |")
    md.append("|---|---|---:|---|")
    for r in results:
        md.append(f"| {r['method']} | {r['path']} | {r['status']} | {r['payload_mode']} |")

    out = "FULL_ENDPOINT_AUDIT.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print("TOTAL", total)
    print("STATUS", by_status)
    print("HARD_FAIL", len(hard_fail))
    for r in hard_fail[:30]:
        print("FAIL", r["method"], r["path"], r["status"])
    print("REPORT", out)


if __name__ == "__main__":
    main()
