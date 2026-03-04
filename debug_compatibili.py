import datetime
import json
from typing import Dict, List, Any

import requests

BASE = "http://localhost:25080"
TIMEOUT = 60


def req(method: str, path: str, body=None):
    r = requests.request(method, BASE + path, json=body, timeout=TIMEOUT)
    try:
        payload = r.json()
    except Exception:
        payload = r.text
    return r.status_code, payload


def get_corse() -> List[Dict[str, Any]]:
    status, body = req("GET", "/corsa/lista")
    if status != 200 or not isinstance(body, list):
        raise RuntimeError(f"/corsa/lista failed: {status} {body}")
    return body


def get_percorsi_by_corsa(corsa_id: str) -> List[Dict[str, Any]]:
    q = f"/percorso/by_corsa/{corsa_id}?order_by=created_at&mode=DESC&limit=100"
    status, body = req("GET", q)
    if status != 200 or not isinstance(body, dict):
        return []
    perc = body.get("percorsi", [])
    return perc if isinstance(perc, list) else []


def parse_dt(value: Any):
    if not value:
        return None
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value)
        except Exception:
            return None
    return value


def expected_compatibili(target_percorsi: List[Dict[str, Any]], assigned_percorsi: List[Dict[str, Any]], assigned_ids: set):
    out = []
    for pc in target_percorsi:
        pc_id = str(pc.get("id") or pc.get("percorso_id"))
        if pc_id in assigned_ids:
            continue

        pc_vasc = str(pc.get("vascello_id")) if pc.get("vascello_id") else None
        pc_start = parse_dt(pc.get("orario_partenza_schedulato"))
        pc_end = parse_dt(pc.get("orario_arrivo_previsto") or pc.get("orario_arrivo_calcolato"))
        if pc_end is None and pc_start and pc.get("tempo_percorrenza") is not None:
            pc_end = pc_start + datetime.timedelta(minutes=float(pc.get("tempo_percorrenza")))

        compatibile = True
        for pa in assigned_percorsi:
            pa_vasc = str(pa.get("vascello_id")) if pa.get("vascello_id") else None
            if pc_vasc != pa_vasc:
                continue
            pa_start = parse_dt(pa.get("orario_partenza_schedulato"))
            pa_end = parse_dt(pa.get("orario_arrivo_previsto") or pa.get("orario_arrivo_calcolato"))
            if pa_end is None and pa_start and pa.get("tempo_percorrenza") is not None:
                pa_end = pa_start + datetime.timedelta(minutes=float(pa.get("tempo_percorrenza")))
            pa_finisce_prima = bool(pa_end and pc_start and pa_end < pc_start)
            pc_finisce_prima = bool(pc_end and pa_start and pc_end < pa_start)
            if not (pa_finisce_prima or pc_finisce_prima):
                compatibile = False
                break

        if compatibile:
            out.append(pc_id)

    return sorted(out)


def main():
    corse = get_corse()
    if len(corse) < 2:
        raise RuntimeError("Servono almeno 2 corse per test utile")

    # materializza percorsi su alcune corse se assenti
    status_v, vascelli = req("GET", "/vascello/lista")
    if status_v == 200 and isinstance(vascelli, list) and vascelli:
        vascello_id = vascelli[0].get("id")
        for c in corse[:3]:
            corsa_id = c.get("id")
            perc = get_percorsi_by_corsa(corsa_id)
            if not perc and vascello_id:
                req("POST", "/weather_routing/carico", {
                    "items": [{
                        "corsa_id": corsa_id,
                        "vascello_id": vascello_id,
                        "eps_time": 5,
                        "fake_data": True,
                        "ve_min": 0.1,
                        "tolerance": 1,
                    }]
                })

    corse_with_perc = []
    for c in corse:
        corsa_id = c.get("id")
        perc = get_percorsi_by_corsa(corsa_id)
        if perc:
            corse_with_perc.append((corsa_id, perc))
        if len(corse_with_perc) >= 2:
            break

    if len(corse_with_perc) < 2:
        raise RuntimeError("Non trovo 2 corse con percorsi per test")

    target_corsa_id, target_percorsi = corse_with_perc[0]
    assigned_corsa_id, assigned_percorsi = corse_with_perc[1]

    assigned_percorso_id = str(assigned_percorsi[0].get("id") or assigned_percorsi[0].get("percorso_id"))

    print("=== TEST 1: caso normale ===")
    payload = {"corsa_id": target_corsa_id, "percorsi_id": [assigned_percorso_id]}
    s1, b1 = req("POST", "/pianificazione/compatibili", payload)
    print("payload:", json.dumps(payload, ensure_ascii=False))
    print("status:", s1)
    if isinstance(b1, dict):
        got_ids = sorted([str(x.get("percorso_id")) for x in b1.get("percorsi_compatibili", [])])
    else:
        got_ids = []
    expected_ids = expected_compatibili(target_percorsi, [assigned_percorsi[0]], {assigned_percorso_id})
    print("got_count:", len(got_ids), "expected_count:", len(expected_ids), "match:", got_ids == expected_ids)

    print("\n=== TEST 2: stessa corsa già assegnata => [] ===")
    same_corsa_assigned_id = str(target_percorsi[0].get("id") or target_percorsi[0].get("percorso_id"))
    payload2 = {"corsa_id": target_corsa_id, "percorsi_id": [same_corsa_assigned_id]}
    s2, b2 = req("POST", "/pianificazione/compatibili", payload2)
    print("payload:", json.dumps(payload2, ensure_ascii=False))
    print("status:", s2)
    print("response:", b2)

    print("\n=== TEST 3: percorso assegnato inesistente => 404 ===")
    payload3 = {
        "corsa_id": target_corsa_id,
        "percorsi_id": ["00000000-0000-0000-0000-000000000000"],
    }
    s3, b3 = req("POST", "/pianificazione/compatibili", payload3)
    print("payload:", json.dumps(payload3, ensure_ascii=False))
    print("status:", s3)
    print("response:", b3)


if __name__ == "__main__":
    main()
