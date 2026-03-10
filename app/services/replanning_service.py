"""
Servizio per il check replanning.
Recupera i dati dai servizi interni e li invia al servizio esterno di replanning.
"""
import httpx
import os
import glob
import json
from datetime import date
from typing import Dict, List, Any, Optional, Literal
from collections import defaultdict
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from fastapi.encoders import jsonable_encoder

from app.core.config import REPLANNING_SERVICE_URL, KAFKA_CONFIG, SERVICE_CONFIG
from app.core.anagrafica_client import get_json as anagrafica_get_json, AnagraficaDelegationError
from app.core.percorsi_client import get_json as percorsi_get_json, PercorsiDelegationError
from app.core.operativo_client import get_json as operativo_get_json, OperativoDelegationError
from app.services import pianificazione_service, assegnazione_service, corsa_service


class PianoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    data_riferimento: date
    stato: Literal["CREATO", "IN_OTTIMIZZAZIONE", "PRONTO", "ATTIVO"]
    descrizione: str = Field(..., min_length=1)


def _build_piano_payload(piano: Dict[str, Any]) -> Dict[str, Any]:
    stato_raw = str(piano.get("stato", "")).upper()
    stato_map = {
        "IN_CORSO": "ATTIVO",
        "ATTIVO": "ATTIVO",
        "IN_OTTIMIZZAZIONE": "IN_OTTIMIZZAZIONE",
        "PRONTO": "PRONTO",
        "CREATO": "CREATO",
        "PIANIFICATO": "PRONTO",
        "COMPLETATO": "ATTIVO",
    }
    stato = stato_map.get(stato_raw, "ATTIVO")

    try:
        piano_model = PianoInput(
            id=str(piano.get("id", "")),
            data_riferimento=piano.get("data_riferimento"),
            stato=stato,
            descrizione=str(piano.get("descrizione") or "Piano operativo giornaliero"),
        )
    except ValidationError as e:
        raise ValueError(f"Piano non conforme a PianoInput: {e}")

    return piano_model.model_dump(mode="json")


def _fetch_piano_by_id(piano_id: str) -> Optional[Dict[str, Any]]:
    try:
        return operativo_get_json(f"/internal/piano/{piano_id}")
    except Exception:
        return pianificazione_service.get_piano_by_id(piano_id)


def _fetch_piani() -> List[Dict[str, Any]]:
    try:
        data = operativo_get_json("/internal/piano/lista")
        return data if isinstance(data, list) else []
    except Exception:
        return pianificazione_service.lista_piani(None)


def _fetch_assegnazioni_by_piano(piano_id: str) -> List[Dict[str, Any]]:
    try:
        data = operativo_get_json(f"/internal/assegnazione/by_piano/{piano_id}")
        return data if isinstance(data, list) else []
    except Exception:
        return assegnazione_service.lista_assegnazioni_by_piano(piano_id)


def _fetch_corsa(corsa_id: str) -> Optional[Dict[str, Any]]:
    try:
        return operativo_get_json(f"/internal/corsa/id/{corsa_id}")
    except Exception:
        try:
            return corsa_service.get_corsa(corsa_id)
        except Exception:
            return None


def get_mmsi_per_vascelli(vascello_ids: List[str]) -> Dict[str, str]:
    if not vascello_ids:
        return {}

    out: Dict[str, str] = {}
    for vascello_id in vascello_ids:
        try:
            vascello = anagrafica_get_json(f"/internal/vascello/{vascello_id}")
            if isinstance(vascello, dict) and vascello.get("mmsi"):
                out[str(vascello_id)] = str(vascello.get("mmsi"))
        except (AnagraficaDelegationError, Exception):
            continue
    return out


def get_percorsi_info(percorso_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not percorso_ids:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for percorso_id in percorso_ids:
        try:
            percorso = percorsi_get_json(f"/internal/percorso/{percorso_id}")
            if not isinstance(percorso, dict):
                continue
            tempo_val = percorso.get("tempo_percorrenza")
            tempo_min = float(tempo_val) if tempo_val is not None else None
            out[str(percorso_id)] = {
                "id": str(percorso_id),
                "tempo_percorrenza_min": tempo_min,
                "consumo": percorso.get("consumo"),
                "comfort": percorso.get("comfort"),
                "vascello_id": percorso.get("vascello_id"),
                "id_corsa": percorso.get("corsa_id"),
            }
        except (PercorsiDelegationError, Exception):
            continue
    return out


def get_piano_in_corso_oggi() -> Optional[Dict[str, Any]]:
    oggi = date.today().isoformat()
    piani = _fetch_piani()

    for piano in piani:
        data_riferimento = piano.get("data_riferimento", "")
        if data_riferimento:
            if hasattr(data_riferimento, "isoformat"):
                data_piano = data_riferimento.isoformat().split("T")[0]
            else:
                data_piano = str(data_riferimento).split("T")[0]
        else:
            data_piano = ""

        stato = str(piano.get("stato", "")).upper()
        if stato in {"IN_CORSO", "ATTIVO"} and data_piano == oggi:
            return piano

    return None


def organizza_assegnazioni_per_vascello(assegnazioni: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    per_vascello = defaultdict(list)

    for assegnazione in assegnazioni:
        vascello_id = assegnazione.get("vascello_id")
        if vascello_id:
            per_vascello[vascello_id].append(assegnazione)

    for vascello_id in per_vascello:
        per_vascello[vascello_id].sort(key=lambda x: x.get("id", ""))

    return dict(per_vascello)


def _get_virtual_simulation_overrides(piano_id: str) -> Dict[str, str]:
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    file_path = os.path.join(data_dir, f"simulazioni_schedulate_{piano_id}.json")

    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    risultati = data.get("risultati", []) if isinstance(data, dict) else []
    orari_per_assegnazione: Dict[str, str] = {}

    for item in risultati:
        if not isinstance(item, dict):
            continue
        assegnazione_id = item.get("assegnazione_id")
        orario_simulazione = item.get("orario_simulazione")
        if assegnazione_id and orario_simulazione:
            orari_per_assegnazione[str(assegnazione_id)] = str(orario_simulazione)

    return orari_per_assegnazione


def get_schedulated_piano_ids() -> List[str]:
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    files = glob.glob(os.path.join(data_dir, "simulazioni_schedulate_*.json"))

    if not files:
        return []

    candidates: List[str] = []
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            piano_id = payload.get("piano_id") if isinstance(payload, dict) else None
            if piano_id:
                candidates.append(str(piano_id))
        except Exception:
            continue

    if not candidates:
        return []

    valid_ids: List[str] = []
    for pid in candidates:
        assegnazioni = _fetch_assegnazioni_by_piano(pid)
        has_valid = any(a.get("stato_esecuzione") in {"PIANIFICATA", "IN_CORSO"} for a in assegnazioni)
        if has_valid:
            valid_ids.append(pid)

    return valid_ids


def run_periodic_replanning_cycle() -> Dict[str, Any]:
    piano_ids = get_schedulated_piano_ids()
    virtual_checks: List[Dict[str, Any]] = []

    for pid in piano_ids:
        try:
            result = check_replanning(virtuale=True, piano_id=pid)
            virtual_checks.append(
                {
                    "piano_id": pid,
                    "success": bool(result.get("success")),
                    "message": result.get("message"),
                }
            )
        except Exception as exc:
            virtual_checks.append(
                {
                    "piano_id": pid,
                    "success": False,
                    "message": f"Errore check virtuale: {exc}",
                }
            )

    try:
        in_corso_check = check_replanning(virtuale=False, piano_id=None)
    except Exception as exc:
        in_corso_check = {
            "success": False,
            "message": f"Errore check piano IN_CORSO non virtuale: {exc}",
            "piano": None,
            "assegnazioni_per_vascello": {},
            "mmsi_per_vascello": {},
        }

    return {
        "success": True,
        "virtual_checks_count": len(virtual_checks),
        "virtual_checks": virtual_checks,
        "in_corso_check": {
            "success": bool(in_corso_check.get("success")),
            "message": in_corso_check.get("message"),
            "piano_id": (in_corso_check.get("piano") or {}).get("id") if isinstance(in_corso_check, dict) else None,
        },
    }


def chiama_servizio_replanning(
    piano: Dict[str, Any],
    assegnazioni_per_vascello: Dict[str, List[Dict[str, Any]]],
    mmsi_per_vascello: Dict[str, str],
) -> Dict[str, Any]:
    assegnazioni_pulite = {}
    for vascello_id, asm_list in assegnazioni_per_vascello.items():
        assegnazioni_pulite[vascello_id] = []
        for a in asm_list:
            asm_clean = {
                "id": a.get("id"),
                "piano_id": a.get("piano_id"),
                "vascello_id": a.get("vascello_id"),
                "percorso_id": a.get("percorso_id"),
                "id_corsa": a.get("id_corsa"),
                "stato_esecuzione": a.get("stato_esecuzione"),
                "virtuale": a.get("virtuale", False),
                "orario_completamento": a.get("orario_completamento"),
                "percorso": a.get("percorso"),
                "corsa": a.get("corsa"),
            }
            assegnazioni_pulite[vascello_id].append(asm_clean)

    payload = {
        "piano": _build_piano_payload(piano),
        "assegnazioni_per_vascello": assegnazioni_pulite,
        "mmsi_per_vascello": mmsi_per_vascello,
        "config_replanning": {
            "theta_min": SERVICE_CONFIG.replanning_theta_min,
            "theta_critical_min": SERVICE_CONFIG.replanning_theta_critical_min,
            "max_late": SERVICE_CONFIG.replanning_max_late,
            "max_critical": SERVICE_CONFIG.replanning_max_critical,
            "total_delay_max": SERVICE_CONFIG.replanning_total_delay_max,
            "single_delay_max": SERVICE_CONFIG.replanning_single_delay_max,
            "horizon_minutes": SERVICE_CONFIG.replanning_horizon_minutes,
            "cooldown_minutes": SERVICE_CONFIG.replanning_cooldown_minutes,
            "freeze_window_minutes": SERVICE_CONFIG.replanning_freeze_window_minutes,
        },
    }
    payload = jsonable_encoder(payload)

    try:
        response = httpx.post(
            f"{REPLANNING_SERVICE_URL}/replanning/check",
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as e:
        return {
            "success": False,
            "error": f"Errore di connessione al servizio di replanning: {str(e)}",
            "message": "indirizzo configurato: " + REPLANNING_SERVICE_URL,
        }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"Errore HTTP dal servizio di replanning: {e.response.status_code}",
        }


def check_replanning(virtuale: bool, piano_id: Optional[str] = None) -> Dict[str, Any]:
    piano = _fetch_piano_by_id(piano_id) if piano_id else get_piano_in_corso_oggi()

    if piano is None:
        message = f"Piano non trovato per id={piano_id}" if piano_id else "Nessun piano IN_CORSO trovato per oggi"
        return jsonable_encoder(
            {
                "success": False,
                "message": message,
                "piano": None,
                "assegnazioni_per_vascello": {},
                "mmsi_per_vascello": {},
            }
        )

    piano_id_value = piano.get("id")
    if not piano_id_value:
        return jsonable_encoder(
            {
                "success": False,
                "message": "Piano di riferimento non valido: campo 'id' mancante",
                "piano": piano,
                "assegnazioni_per_vascello": {},
                "mmsi_per_vascello": {},
            }
        )

    assegnazioni = _fetch_assegnazioni_by_piano(str(piano_id_value))
    assegnazioni = [a for a in assegnazioni if bool(a.get("virtuale")) is virtuale]

    stati_validi = {"PIANIFICATA", "IN_CORSO", "COMPLETATA"}
    assegnazioni = [a for a in assegnazioni if a.get("stato_esecuzione") in stati_validi]

    assegnazioni_per_vascello = organizza_assegnazioni_per_vascello(assegnazioni)

    vascello_ids = list(assegnazioni_per_vascello.keys())
    mmsi_per_vascello = get_mmsi_per_vascelli(vascello_ids)

    percorso_ids = set()
    corsa_ids = set()
    for asm_list in assegnazioni_per_vascello.values():
        for a in asm_list:
            if a.get("percorso_id"):
                percorso_ids.add(a["percorso_id"])
            if a.get("id_corsa"):
                corsa_ids.add(a["id_corsa"])

    percorsi_info = get_percorsi_info(list(percorso_ids))

    corse_info: Dict[str, Any] = {}
    for cid in corsa_ids:
        corse_info[cid] = _fetch_corsa(cid)

    sim_orari_per_assegnazione: Dict[str, str] = {}
    sim_speed_factor = float(KAFKA_CONFIG.get("sim_speed_factor", 1.0) or 1.0)
    if sim_speed_factor <= 0:
        sim_speed_factor = 1.0
    if virtuale:
        sim_orari_per_assegnazione = _get_virtual_simulation_overrides(str(piano_id_value))

    for asm_list in assegnazioni_per_vascello.values():
        for a in asm_list:
            pid = a.get("percorso_id")
            cid = a.get("id_corsa")
            a["percorso"] = percorsi_info.get(pid)
            a["corsa"] = corse_info.get(cid)

            if virtuale:
                assegnazione_id = str(a.get("id")) if a.get("id") else None
                orario_simulazione = sim_orari_per_assegnazione.get(assegnazione_id) if assegnazione_id else None

                if orario_simulazione and isinstance(a.get("corsa"), dict):
                    a["corsa"]["orario_partenza_schedulato"] = orario_simulazione

                percorso = a.get("percorso")
                if isinstance(percorso, dict) and percorso.get("tempo_percorrenza_min") is not None and sim_speed_factor > 0:
                    percorso["tempo_percorrenza_min"] = float(percorso["tempo_percorrenza_min"]) / sim_speed_factor

    risposta_replanning = chiama_servizio_replanning(piano, assegnazioni_per_vascello, mmsi_per_vascello)

    return jsonable_encoder(
        {
            "success": True,
            "message": f"Piano di riferimento elaborato con {len(assegnazioni)} assegnazioni (virtuale={virtuale}) su {len(assegnazioni_per_vascello)} vascelli",
            "piano": piano,
            "assegnazioni_per_vascello": assegnazioni_per_vascello,
            "mmsi_per_vascello": mmsi_per_vascello,
            "risposta_replanning": risposta_replanning,
        }
    )
