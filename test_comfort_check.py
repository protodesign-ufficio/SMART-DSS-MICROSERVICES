import requests, json

payload = {
    "vessel": {"id": "test_v", "name": "Test", "length_m": 30.0, "vmax_knots": 12},
    "start": {"lat": 40.65, "lon": 14.25},
    "goal": {"lat": 40.55, "lon": 14.70},
    "params": {
        "start_time_utc": "2026-02-25T09:30:00",
        "time_max": 7200,
        "vel_vect_knots": [4, 6, 8, 10]
    },
    "optimization_id": "test_comfort",
    "empty": False,
    "tollerance": 60
}
r = requests.post("http://localhost:8090/optimize/list", json=[payload], timeout=300)
print("STATUS:", r.status_code)
data = r.json()
import json as j
print("RAW:", j.dumps(data, indent=2)[:2000])
if isinstance(data, list) and len(data) > 0:
    for route in data[:5]:
        print(f"comfort={route.get('comfort','-')} fuel={route.get('fuel_kg','-')} time={route.get('travel_time_h','-')}")
else:
    print("RESPONSE:", json.dumps(data, indent=2)[:500])
