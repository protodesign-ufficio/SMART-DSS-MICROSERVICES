"""
Confronto interattivo Dati Reali vs Scenario what-if — Leaflet.

Genera una pagina HTML con 3 pannelli sincronizzati:
  A) Dati reali (Copernicus via Weather Service)
  B) Dati scenario (Copernicus + modificatore)
  C) Mappa differenza (colore = |scenario − reale|)

Uso:
  # Preset "storm"
  python test_scenario.py --preset storm

  # Preset con timestamp custom
  python test_scenario.py --preset rough_sea --timestamp 2026-03-05T15:00

  # Scenario custom (multiplier + funzione)
  python test_scenario.py --multiplier 3.0 --function gaussian_peak \
      --function-params '{"radius_deg":0.2,"peak_factor":4.0}'

  # Lista preset disponibili
  python test_scenario.py --list-presets

Requisiti: pip install requests
"""

import argparse
import json
import math
import os
import sys

import requests

BASE_URL_DEFAULT = "http://localhost:18076"
DEFAULT_BOUNDS = {"north": 40.76, "south": 40.50, "east": 14.90, "west": 14.30}
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validation_plots")


def fetch_layer(base_url, layer_type, timestamp, scenario=None):
    body = {
        "layer_type": layer_type,
        "timestamp": timestamp,
        "use_cache": False,
        "force_refresh": True,
    }
    if scenario:
        body["scenario"] = scenario
    r = requests.post(f"{base_url}/internal/weather/layer", json=body)
    r.raise_for_status()
    return r.json()


def fetch_presets(base_url):
    r = requests.get(f"{base_url}/internal/weather/scenarios")
    r.raise_for_status()
    return r.json()["presets"]


def generate_scenario_leaflet(
    real_cur, scen_cur,
    real_wav, scen_wav,
    timestamp, bounds, scenario_info, scenario_label, out_path,
):
    """Genera HTML self-contained: 3 pannelli Leaflet — Reale | Scenario | Differenza."""

    center_lat = (bounds["north"] + bounds["south"]) / 2
    center_lon = (bounds["east"] + bounds["west"]) / 2
    scenario_desc = json.dumps(scenario_info, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scenario: {scenario_label} — {timestamp}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#1a1a2e;color:#eee}}
.header{{background:#16213e;padding:12px 20px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}}
.header h1{{font-size:16px;color:#4fc3f7}}
.header .info{{font-size:12px;color:#aaa}}
.controls{{background:#0f3460;padding:8px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
.controls label{{font-size:13px;cursor:pointer}}
.controls input[type="checkbox"]{{margin-right:4px}}
.btn{{padding:4px 12px;border:1px solid #4fc3f7;background:transparent;color:#4fc3f7;
      border-radius:4px;cursor:pointer;font-size:12px}}
.btn:hover{{background:#4fc3f7;color:#000}}
.btn.active{{background:#4fc3f7;color:#000}}
.map-container{{display:flex;height:calc(100vh - 90px)}}
.map-panel{{flex:1;position:relative;border-right:2px solid #0f3460}}
.map-panel:last-child{{border-right:none}}
.map-panel .map{{width:100%;height:100%}}
.map-label{{position:absolute;top:8px;left:50px;z-index:1000;background:rgba(15,52,96,0.9);
            padding:6px 14px;border-radius:4px;font-size:13px;font-weight:bold;pointer-events:none}}
.map-label.real{{color:#4fc3f7;border:1px solid #4fc3f7}}
.map-label.scen{{color:#f7c948;border:1px solid #f7c948}}
.map-label.diff{{color:#ff6b6b;border:1px solid #ff6b6b}}
.stats-box{{position:absolute;bottom:25px;left:10px;z-index:1000;background:rgba(0,0,0,0.85);
            padding:8px 12px;border-radius:6px;font-size:11px;line-height:1.5;max-width:220px}}
.legend{{position:absolute;bottom:25px;right:10px;z-index:1000;background:rgba(0,0,0,0.8);
         padding:8px 12px;border-radius:6px;font-size:11px;line-height:1.6}}
.legend .bar{{width:80px;height:12px;border-radius:2px;display:inline-block;vertical-align:middle}}
</style>
</head>
<body>
<div class="header">
  <h1>&#9889; Scenario: {scenario_label}</h1>
  <span class="info">Timestamp: <b>{timestamp}</b> | {scenario_desc}</span>
</div>
<div class="controls">
  <span style="font-size:13px;font-weight:bold;color:#4fc3f7">Layer:</span>
  <button class="btn active" onclick="showLayer('currents')">Correnti</button>
  <button class="btn" onclick="showLayer('waves')">Onde</button>
  <span style="margin-left:16px;font-size:13px;font-weight:bold;color:#4fc3f7">Mostra:</span>
  <label><input type="checkbox" id="chkArrows" checked onchange="redraw()"> Frecce</label>
  <label><input type="checkbox" id="chkMag" checked onchange="redraw()"> Intensità</label>
  <label><input type="checkbox" id="chkSync" checked> Sync mappe</label>
</div>
<div class="map-container">
  <div class="map-panel">
    <div class="map-label real">A) Dati reali</div>
    <div id="map-real" class="map"></div>
    <div id="stats-real" class="stats-box"></div>
  </div>
  <div class="map-panel">
    <div class="map-label scen">B) Scenario: {scenario_label}</div>
    <div id="map-scen" class="map"></div>
    <div id="stats-scen" class="stats-box"></div>
  </div>
  <div class="map-panel">
    <div class="map-label diff">C) Differenza |S − R|</div>
    <div id="map-diff" class="map"></div>
    <div id="stats-diff" class="stats-box"></div>
    <div id="legend-diff" class="legend"></div>
  </div>
</div>

<script>
const DATA = {{
  currents: {{
    real: {json.dumps(real_cur)},
    scen: {json.dumps(scen_cur)}
  }},
  waves: {{
    real: {json.dumps(real_wav)},
    scen: {json.dumps(scen_wav)}
  }}
}};

let currentLayer = 'currents';
let mapReal, mapScen, mapDiff;
let lyReal=[], lyScen=[], lyDiff=[];
let syncing = false;

function initMaps() {{
  const opts = {{ zoomControl: true }};
  const c = [{center_lat},{center_lon}];
  mapReal = L.map('map-real', opts).setView(c, 11);
  mapScen = L.map('map-scen', opts).setView(c, 11);
  mapDiff = L.map('map-diff', opts).setView(c, 11);

  const tiles = 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png';
  const attr = '&copy; OpenStreetMap &copy; CARTO';
  [mapReal, mapScen, mapDiff].forEach(m => L.tileLayer(tiles, {{attribution:attr,maxZoom:18}}).addTo(m));

  function syncAll(src) {{
    if (syncing || !document.getElementById('chkSync').checked) return;
    syncing = true;
    const center = src.getCenter(), zoom = src.getZoom();
    [mapReal, mapScen, mapDiff].forEach(m => {{
      if (m !== src) m.setView(center, zoom, {{animate:false}});
    }});
    syncing = false;
  }}
  [mapReal, mapScen, mapDiff].forEach(m => m.on('move', () => syncAll(m)));

  redraw();
}}

function clear() {{
  lyReal.forEach(l => mapReal.removeLayer(l)); lyReal=[];
  lyScen.forEach(l => mapScen.removeLayer(l)); lyScen=[];
  lyDiff.forEach(l => mapDiff.removeLayer(l)); lyDiff=[];
}}

/* ── Color helpers ── */
function magColor(t) {{
  const r = Math.round(34 + t*221);
  const g = Math.round(139 + (1 - Math.abs(t-0.5)*2)*116);
  const b = Math.round(230 - t*180);
  return `rgb(${{r}},${{g}},${{b}})`;
}}
function waveColor(t) {{
  return `rgb(${{Math.round(255*t)}},${{Math.round(255*(1-t)*0.8)}},50)`;
}}
function diffColor(t) {{
  /* 0 = verde (nessuna diff), 1 = rosso (max diff) */
  const r = Math.round(40 + 215*t);
  const g = Math.round(200 - 170*t);
  const b = Math.round(60 - 30*t);
  return `rgb(${{r}},${{g}},${{b}})`;
}}

/* ── Stats ── */
function curMag(it) {{ return Math.sqrt(it.u*it.u + it.v*it.v); }}

function statsHTML(items, type, label) {{
  if (!items.length) return '';
  if (type === 'currents') {{
    const ms = items.map(curMag);
    return `<b>${{label}} — Correnti</b><br>N=${{items.length}}`
      + `<br>|V| min: ${{Math.min(...ms).toFixed(5)}} m/s`
      + `<br>|V| max: ${{Math.max(...ms).toFixed(5)}} m/s`
      + `<br>|V| mean: ${{(ms.reduce((a,b)=>a+b,0)/ms.length).toFixed(5)}} m/s`;
  }}
  const hs = items.map(it => it.height);
  return `<b>${{label}} — Onde</b><br>N=${{items.length}}`
    + `<br>H min: ${{Math.min(...hs).toFixed(4)}} m`
    + `<br>H max: ${{Math.max(...hs).toFixed(4)}} m`
    + `<br>H mean: ${{(hs.reduce((a,b)=>a+b,0)/hs.length).toFixed(4)}} m`;
}}

/* ── Draw functions ── */
function drawArrow(map, lat, lon, dlat, dlon, color, arr) {{
  const endLat = lat+dlat, endLon = lon+dlon;
  const line = L.polyline([[lat,lon],[endLat,endLon]], {{color:color,weight:1.5,opacity:0.8}}).addTo(map);
  arr.push(line);
  const angle = Math.atan2(dlat, dlon), hl = 0.006;
  const head = L.polyline(
    [[endLat-hl*Math.sin(angle-0.5),endLon-hl*Math.cos(angle-0.5)],
     [endLat,endLon],
     [endLat-hl*Math.sin(angle+0.5),endLon-hl*Math.cos(angle+0.5)]],
    {{color:color,weight:1.5,opacity:0.8}}
  ).addTo(map);
  arr.push(head);
}}

function drawCurrents(map, items, arr, colFn, globalMin, globalMax) {{
  const arrows = document.getElementById('chkArrows').checked;
  const mag = document.getElementById('chkMag').checked;
  items.forEach(it => {{
    const m = curMag(it);
    const t = globalMax > globalMin ? (m-globalMin)/(globalMax-globalMin) : 0;
    if (mag) {{
      const c = L.circleMarker([it.lat,it.lon], {{
        radius:6, fillColor:colFn(t), fillOpacity:0.75, stroke:false
      }}).addTo(map);
      c.bindPopup(`<b>Corrente</b><br>lat:${{it.lat.toFixed(4)}}<br>lon:${{it.lon.toFixed(4)}}<br>u:${{it.u.toFixed(5)}}<br>v:${{it.v.toFixed(5)}}<br>|V|:${{m.toFixed(5)}} m/s`);
      arr.push(c);
    }}
    if (arrows && m > 1e-6) {{
      const sc=0.03, f=Math.min(m*8,0.4);
      drawArrow(map, it.lat, it.lon, it.v*sc/m*f, it.u*sc/m*f, '#fff', arr);
    }}
  }});
}}

function drawWaves(map, items, arr, colFn, globalMin, globalMax) {{
  const arrows = document.getElementById('chkArrows').checked;
  const mag = document.getElementById('chkMag').checked;
  items.forEach(it => {{
    const t = globalMax > globalMin ? (it.height-globalMin)/(globalMax-globalMin) : 0;
    if (mag) {{
      const r = 4 + t*8;
      const c = L.circleMarker([it.lat,it.lon], {{
        radius:r, fillColor:colFn(t), fillOpacity:0.75, stroke:true, color:'#fff', weight:0.5
      }}).addTo(map);
      c.bindPopup(`<b>Onda</b><br>lat:${{it.lat.toFixed(4)}}<br>lon:${{it.lon.toFixed(4)}}<br>H:${{it.height.toFixed(4)}} m<br>Dir:${{it.dir.toFixed(1)}}°<br>T:${{it.period.toFixed(3)}} s`);
      arr.push(c);
    }}
    if (arrows) {{
      const rad = (270-it.dir)*Math.PI/180;
      const len = 0.015 + t*0.02;
      drawArrow(map, it.lat, it.lon, Math.sin(rad)*len, Math.cos(rad)*len, '#f7c948', arr);
    }}
  }});
}}

/* ── Difference layer ── */
function drawDiff(map, realItems, scenItems, type, arr) {{
  const diffs = [];
  const n = Math.min(realItems.length, scenItems.length);
  for (let i = 0; i < n; i++) {{
    const ri = realItems[i], si = scenItems[i];
    let dv;
    if (type === 'currents') {{
      const mR = curMag(ri), mS = curMag(si);
      dv = Math.abs(mS - mR);
    }} else {{
      dv = Math.abs(si.height - ri.height);
    }}
    diffs.push({{ lat:ri.lat, lon:ri.lon, dv:dv, ri:ri, si:si }});
  }}
  if (!diffs.length) return;

  const maxD = Math.max(...diffs.map(d => d.dv));
  const meanD = diffs.reduce((a,d) => a+d.dv, 0) / diffs.length;
  const rmse = Math.sqrt(diffs.reduce((a,d) => a+d.dv*d.dv, 0) / diffs.length);

  diffs.forEach(d => {{
    const t = maxD > 0 ? d.dv / maxD : 0;
    const r = 5 + t * 7;
    const c = L.circleMarker([d.lat, d.lon], {{
      radius: r, fillColor: diffColor(t), fillOpacity: 0.8,
      stroke: true, color: '#fff', weight: 0.3
    }}).addTo(map);
    let popup;
    if (type === 'currents') {{
      popup = `<b>Δ Corrente</b><br>|V| reale: ${{curMag(d.ri).toFixed(5)}}<br>|V| scenario: ${{curMag(d.si).toFixed(5)}}<br><b>Δ = ${{d.dv.toFixed(5)}} m/s</b>`;
    }} else {{
      popup = `<b>Δ Onda</b><br>H reale: ${{d.ri.height.toFixed(4)}}<br>H scenario: ${{d.si.height.toFixed(4)}}<br><b>Δ = ${{d.dv.toFixed(4)}} m</b>`;
    }}
    c.bindPopup(popup);
    arr.push(c);
  }});

  const unit = type === 'currents' ? 'm/s' : 'm';
  document.getElementById('stats-diff').innerHTML =
    `<b>Differenza |S−R|</b><br>N=${{diffs.length}}`
    + `<br>max Δ: ${{maxD.toFixed(5)}} ${{unit}}`
    + `<br>mean Δ: ${{meanD.toFixed(5)}} ${{unit}}`
    + `<br>RMSE: ${{rmse.toFixed(5)}} ${{unit}}`;

  document.getElementById('legend-diff').innerHTML =
    `<div style="display:flex;align-items:center;gap:6px"><span class="bar" style="background:linear-gradient(to right,rgb(40,200,60),rgb(255,30,30))"></span>`
    + `<span>0 → ${{maxD.toFixed(4)}} ${{unit}}</span></div>`;
}}

/* ── Main redraw ── */
function redraw() {{
  clear();
  const ri = DATA[currentLayer].real;
  const si = DATA[currentLayer].scen;

  /* Compute global min/max across both real & scenario for consistent coloring */
  let allVals;
  if (currentLayer === 'currents') {{
    allVals = ri.map(curMag).concat(si.map(curMag));
  }} else {{
    allVals = ri.map(it=>it.height).concat(si.map(it=>it.height));
  }}
  const gMin = Math.min(...allVals), gMax = Math.max(...allVals);

  if (currentLayer === 'currents') {{
    drawCurrents(mapReal, ri, lyReal, magColor, gMin, gMax);
    drawCurrents(mapScen, si, lyScen, magColor, gMin, gMax);
  }} else {{
    drawWaves(mapReal, ri, lyReal, waveColor, gMin, gMax);
    drawWaves(mapScen, si, lyScen, waveColor, gMin, gMax);
  }}

  drawDiff(mapDiff, ri, si, currentLayer, lyDiff);

  document.getElementById('stats-real').innerHTML = statsHTML(ri, currentLayer, 'Reale');
  document.getElementById('stats-scen').innerHTML = statsHTML(si, currentLayer, 'Scenario');
}}

function showLayer(type) {{
  currentLayer = type;
  document.querySelectorAll('.controls .btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  redraw();
}}

document.addEventListener('DOMContentLoaded', initMaps);
</script>
</body>
</html>"""

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Salvato: {out_path}")


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Confronto Reale vs Scenario — Leaflet")
    parser.add_argument("--service-url", default=BASE_URL_DEFAULT)
    parser.add_argument("--timestamp", default="2026-03-05T12:00")
    parser.add_argument("--preset", help="Nome preset scenario (es. storm, rough_sea)")
    parser.add_argument("--multiplier", type=float, help="Fattore moltiplicativo custom")
    parser.add_argument("--function", dest="func", help="Funzione: sinusoidal|linear_ramp|gaussian_peak")
    parser.add_argument("--function-params", dest="fparams", help="JSON parametri funzione")
    parser.add_argument("--variables", help="Variabili target comma-separated (es. u,v)")
    parser.add_argument("--list-presets", action="store_true", help="Mostra preset disponibili ed esce")
    args = parser.parse_args()

    base = args.service_url

    # ── List presets ──
    if args.list_presets:
        presets = fetch_presets(base)
        print("Preset disponibili:")
        for k, v in presets.items():
            print(f"  {k:25s} {v['label']} — {v['description']}")
        return

    # ── Build scenario ──
    scenario_label = "custom"
    if args.preset:
        presets = fetch_presets(base)
        if args.preset not in presets:
            print(f"Preset '{args.preset}' non trovato. Disponibili: {', '.join(presets.keys())}")
            sys.exit(1)
        scenario = presets[args.preset]["scenario"]
        scenario_label = presets[args.preset]["label"]
        print(f"Preset: {args.preset} — {presets[args.preset]['description']}")
    else:
        scenario = {}
        if args.multiplier is not None:
            scenario["multiplier"] = args.multiplier
            scenario_label = f"×{args.multiplier}"
        if args.func:
            scenario["function"] = args.func
            scenario_label += f" + {args.func}"
        if args.fparams:
            scenario["function_params"] = json.loads(args.fparams)
        if args.variables:
            scenario["variables"] = [v.strip() for v in args.variables.split(",")]
        if not scenario:
            print("Specificare --preset oppure --multiplier / --function")
            parser.print_help()
            sys.exit(1)

    print(f"Scenario: {json.dumps(scenario, ensure_ascii=False)}")
    print(f"Timestamp: {args.timestamp}")
    print()

    # ── Fetch data ──
    print("[1/4] Fetch correnti reali...")
    real_cur = fetch_layer(base, "currents", args.timestamp)
    print(f"       items={len(real_cur['items'])}")

    print("[2/4] Fetch correnti scenario...")
    scen_cur = fetch_layer(base, "currents", args.timestamp, scenario)
    print(f"       items={len(scen_cur['items'])}")

    print("[3/4] Fetch onde reali...")
    real_wav = fetch_layer(base, "waves", args.timestamp)
    print(f"       items={len(real_wav['items'])}")

    print("[4/4] Fetch onde scenario...")
    scen_wav = fetch_layer(base, "waves", args.timestamp, scenario)
    print(f"       items={len(scen_wav['items'])}")

    # ── Console summary ──
    print()
    for lt, rd, sd in [("currents", real_cur, scen_cur), ("waves", real_wav, scen_wav)]:
        print(f"  {lt.upper()}: reale range [{rd['range']['min']:.5f}, {rd['range']['max']:.5f}]"
              f"  scenario range [{sd['range']['min']:.5f}, {sd['range']['max']:.5f}]")

    # ── Generate Leaflet HTML ──
    tag = args.timestamp.replace(":", "").replace("-", "")
    preset_tag = args.preset if args.preset else "custom"
    out_path = os.path.join(OUTPUT_DIR, f"scenario_{preset_tag}_{tag}.html")

    print()
    print("Generazione mappa Leaflet...")
    generate_scenario_leaflet(
        real_cur=real_cur["items"],
        scen_cur=scen_cur["items"],
        real_wav=real_wav["items"],
        scen_wav=scen_wav["items"],
        timestamp=args.timestamp,
        bounds=DEFAULT_BOUNDS,
        scenario_info=scenario,
        scenario_label=scenario_label,
        out_path=out_path,
    )
    print("Fatto!")


if __name__ == "__main__":
    main()
