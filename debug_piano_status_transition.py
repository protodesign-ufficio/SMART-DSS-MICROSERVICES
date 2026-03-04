import datetime
import json
import requests

def resolve_base_url():
    for port in (25080, 18000):
        base = f"http://localhost:{port}"
        try:
            r = requests.get(base + "/openapi.json", timeout=3)
            if r.status_code == 200:
                return base
        except Exception:
            continue
    raise RuntimeError("Gateway non raggiungibile su localhost:25080 o localhost:18000")


BASE = resolve_base_url()


def req(method, path, body=None):
    r = requests.request(method, BASE + path, json=body, timeout=60)
    try:
        payload = r.json()
    except Exception:
        payload = r.text
    return r.status_code, payload


def pick_existing_ids():
    s_v, b_v = req("GET", "/vascello/lista")
    s_c, b_c = req("GET", "/corsa/lista")
    if s_v != 200 or not isinstance(b_v, list) or not b_v:
        raise RuntimeError("Nessun vascello disponibile")
    if s_c != 200 or not isinstance(b_c, list) or not b_c:
        raise RuntimeError("Nessuna corsa disponibile")
    return b_v[0]["id"], b_c[0]["id"]


def ensure_percorso(corsa_id, vascello_id):
    s, b = req("POST", "/weather_routing/carico", {
        "items": [{
            "corsa_id": corsa_id,
            "vascello_id": vascello_id,
            "eps_time": 5,
            "fake_data": True,
            "ve_min": 0.1,
            "tolerance": 1,
        }]
    })
    if s != 200:
        raise RuntimeError(f"weather_routing/carico fallita: {s} {b}")

    s2, b2 = req("GET", f"/percorso/by_corsa/{corsa_id}?order_by=created_at&mode=DESC&limit=1&vascello_id={vascello_id}")
    if s2 != 200 or not isinstance(b2, dict) or not b2.get("percorsi"):
        raise RuntimeError(f"Nessun percorso trovato dopo carico: {s2} {b2}")
    return b2["percorsi"][0]["id"]


def main():
    vascello_id, corsa_id = pick_existing_ids()
    percorso_id = ensure_percorso(corsa_id, vascello_id)

    now = datetime.datetime.now().replace(microsecond=0)
    s_create, b_create = req("POST", "/piano/crea", {
        "data_riferimento": now.isoformat(),
        "stato": "CREATO",
        "kpi_profitto_stimato": 0,
        "kpi_robustezza": 0,
        "versione": 1
    })
    if s_create != 200:
        raise RuntimeError(f"/piano/crea failed: {s_create} {b_create}")

    piano_id = b_create["id"]
    print("piano_creato:", piano_id, "stato:", b_create.get("stato"))

    s_ass, b_ass = req("POST", "/assegnazione/crea", {
        "piano_id": piano_id,
        "percorso_id": percorso_id,
        "stato_esecuzione": "PIANIFICATA",
        "virtuale": False
    })
    if s_ass != 200:
        raise RuntimeError(f"/assegnazione/crea failed: {s_ass} {b_ass}")

    s_get, b_get = req("GET", f"/piano/{piano_id}")
    if s_get != 200:
        raise RuntimeError(f"/piano/{{id}} failed: {s_get} {b_get}")

    print("stato_dopo_assegnazione:", b_get.get("stato"))
    print(json.dumps({"piano_id": piano_id, "stato_finale": b_get.get("stato"), "assegnazione_id": b_ass.get("id")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
