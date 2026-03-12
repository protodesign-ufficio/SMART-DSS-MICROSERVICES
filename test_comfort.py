import requests, json
payload = [{
    "vessel": {"id": "test-vessel", "name": "Vessel Test", "length_m": 30.0, "vmax_knots": 10},
    "start": {"lat": 40.65, "lon": 14.27},
    "goal": {"lat": 40.55, "lon": 14.75},
    "params": {"start_time_utc": "2026-03-12T07:30:00", "time_max": 3600, "vel_vect_knots": [2, 4, 6, 8, 10]},
    "optimization_id": "test_003",
    "ve_min": 0.1,
    "eps_time": 5,
    "empty": False,
    "fake_data": False,
    "tollerance": 60
}]
r = requests.post("http://localhost:8090/optimize/list", json=payload, timeout=300)
print("Status:", r.status_code)
resp = r.json()
if isinstance(resp, list):
    for route_result in resp:
        if isinstance(route_result, dict) and "percorsi" in route_result:
            for p in route_result.get("percorsi", []):
                print(f"  comfort={p.get('comfort')}, tempo={p.get('tempo_percorrenza')}")
        else:
            print("Route result:", json.dumps(route_result, indent=2)[:500])
else:
    print("Response:", json.dumps(resp, indent=2)[:1000])
