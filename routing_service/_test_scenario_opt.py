"""Quick test: compare optimizer output with and without scenario."""
import requests

BASE = "http://localhost:18090/optimize"
COMMON = {
    "vessel": {"id": "test-v1", "name": "TestNave", "length_m": 30, "vmax_knots": 10},
    "start": {"lat": 40.65, "lon": 14.28},
    "goal": {"lat": 40.63, "lon": 14.50},
    "params": {
        "start_time_utc": "2026-03-05T12:00:00",
        "time_max": 3600,
        "vel_vect_knots": [2, 4, 6, 8, 10],
    },
    "fake_data": True,
    "tollerance": 60,
}

# Senza scenario
r1 = requests.post(BASE, json={**COMMON, "optimization_id": "no_scen"}, timeout=120)
d1 = r1.json()
p1 = d1["percorsi"][0]

# Con scenario x3
r2 = requests.post(
    BASE,
    json={**COMMON, "optimization_id": "with_scen", "scenario": {"multiplier": 3.0}},
    timeout=120,
)
d2 = r2.json()
p2 = d2["percorsi"][0]

print(f"SENZA scenario: tempo={p1['tempo_percorrenza']:.1f} min  comfort={p1['comfort']:.2f}  distanza={p1['distanza_nm']:.2f} NM")
print(f"CON scenario x3: tempo={p2['tempo_percorrenza']:.1f} min  comfort={p2['comfort']:.2f}  distanza={p2['distanza_nm']:.2f} NM")
