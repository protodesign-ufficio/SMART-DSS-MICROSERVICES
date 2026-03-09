"""
Servizio esterno di Replanning.
Riceve i dati dall'API Gateway, legge delta ETA dai messaggi Kafka già presenti
e calcola gli indicatori globali di stabilità operativa descritti in specifiche.md.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from faststream.kafka import KafkaBroker
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import (
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC_ANALYTICS,
    KAFKA_TOPIC_NOTIFICATIONS,
    REPLANNING_COOLDOWN_MINUTES,
    REPLANNING_FREEZE_WINDOW_MINUTES,
    REPLANNING_HORIZON_MINUTES,
    REPLANNING_MAX_CRITICAL,
    REPLANNING_MAX_LATE,
    REPLANNING_SINGLE_DELAY_MAX,
    REPLANNING_THETA_CRITICAL_MIN,
    REPLANNING_THETA_MIN,
    REPLANNING_TOTAL_DELAY_MAX,
    SERVICE_HOST,
    SERVICE_PORT,
)


broker = KafkaBroker(KAFKA_BOOTSTRAP_SERVERS)
logger = logging.getLogger("replanning_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

ROME_TZ = ZoneInfo("Europe/Rome")

last_replanning_trigger_at: Optional[datetime] = None
replanning_state_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.start()
    logger.info("Kafka broker connesso", extra={"bootstrap_servers": KAFKA_BOOTSTRAP_SERVERS})
    yield
    await broker.close()
    logger.info("Kafka broker disconnesso")


app = FastAPI(
    title="Replanning Service",
    description="Servizio esterno di ri-pianificazione operativa",
    version="1.1.0",
    lifespan=lifespan,
)


class ReplanningCheckInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "piano": {
                    "id": "uuid-piano-123",
                    "data_riferimento": "2026-02-18",
                    "stato": "IN_CORSO",
                    "descrizione": "Piano operativo giornaliero",
                },
                "assegnazioni_per_vascello": {
                    "uuid-vascello-001": [
                        {
                            "id": "uuid-assegnazione-1",
                            "piano_id": "uuid-piano-123",
                            "vascello_id": "uuid-vascello-001",
                            "percorso_id": "uuid-percorso-11",
                            "id_corsa": "uuid-corsa-1",
                            "stato_esecuzione": "PIANIFICATA",
                            "virtuale": False,
                            "orario_completamento": None,
                            "percorso": {
                                "id": "uuid-percorso-11",
                                "tempo_percorrenza_min": 45.0,
                                "consumo": 125.0,
                                "comfort": 87.0,
                                "vascello_id": "uuid-vascello-001",
                                "id_corsa": "uuid-corsa-1",
                            },
                            "corsa": {
                                "id": "uuid-corsa-1",
                                "nome": "TrattaA-20260218-0800",
                                "tratta_id": "uuid-tratta-1",
                                "tratta_nome": "TrattaA",
                                "orario_partenza_schedulato": "2026-02-18T08:00:00",
                                "previsione_domanda_id": "uuid-prev-1",
                                "orario_arrivo_max": "2026-02-18T09:00:00",
                                "previsione": {
                                    "id": "uuid-prev-1",
                                    "passeggeri_stimati": 206.0,
                                    "confidenza_min": 198.0,
                                    "confidenza_max": 215.0,
                                },
                            },
                        }
                    ]
                },
                "mmsi_per_vascello": {
                    "uuid-vascello-001": "247123456",
                    "uuid-vascello-002": "247789012",
                },
            }
        },
    )

    class PianoInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        id: str = Field(..., min_length=1, examples=["uuid-piano-123"])
        data_riferimento: date = Field(..., examples=["2026-02-18"])
        stato: Literal["ATTIVO", "PIANIFICATO", "IN_CORSO", "COMPLETATO"] = Field(..., examples=["IN_CORSO"])
        descrizione: str = Field(..., min_length=1, examples=["Piano operativo giornaliero"])

    class PercorsoInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        id: str = Field(..., min_length=1, examples=["uuid-percorso-11"])
        tempo_percorrenza_min: float = Field(..., gt=0, examples=[45.0])
        consumo: Optional[float] = Field(default=None, ge=0)
        comfort: Optional[float] = Field(default=None, ge=0)
        vascello_id: str = Field(..., min_length=1, examples=["uuid-vascello-001"])
        id_corsa: str = Field(..., min_length=1, examples=["uuid-corsa-1"])

    class PrevisioneInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        id: str = Field(..., min_length=1, examples=["uuid-prev-1"])
        passeggeri_stimati: Optional[float] = Field(default=None, ge=0)
        confidenza_min: Optional[float] = Field(default=None, ge=0)
        confidenza_max: Optional[float] = Field(default=None, ge=0)

    class CorsaInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        id: str = Field(..., min_length=1, examples=["uuid-corsa-1"])
        nome: Optional[str] = Field(default=None, examples=["TrattaA-20260218-0800"])
        tratta_id: Optional[str] = Field(default=None, examples=["uuid-tratta-1"])
        tratta_nome: Optional[str] = Field(default=None, examples=["CET-SAL"])
        orario_partenza_schedulato: datetime = Field(..., examples=["2026-02-18T08:00:00"])
        previsione_domanda_id: Optional[str] = Field(default=None, examples=["uuid-prev-1"])
        orario_arrivo_max: Optional[datetime] = Field(default=None, examples=["2026-02-18T09:00:00"])
        previsione: Optional["ReplanningCheckInput.PrevisioneInput"] = None

    class AssegnazioneInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        id: str = Field(..., min_length=1, examples=["uuid-assegnazione-1"])
        piano_id: str = Field(..., min_length=1, examples=["uuid-piano-123"])
        vascello_id: str = Field(..., min_length=1, examples=["uuid-vascello-001"])
        percorso_id: str = Field(..., min_length=1, examples=["uuid-percorso-11"])
        id_corsa: str = Field(..., min_length=1, examples=["uuid-corsa-1"])
        stato_esecuzione: Literal["PIANIFICATA", "IN_CORSO", "COMPLETATA"] = Field(..., examples=["IN_CORSO"])
        virtuale: bool = Field(default=False)
        orario_completamento: Optional[datetime] = Field(default=None, examples=["2026-02-18T08:30:00"])
        percorso: "ReplanningCheckInput.PercorsoInput"
        corsa: "ReplanningCheckInput.CorsaInput"
        #deadhead_min: float = Field(default=0, ge=0, examples=[0])

    piano: PianoInput
    assegnazioni_per_vascello: Dict[str, List[AssegnazioneInput]]
    mmsi_per_vascello: Dict[str, str]

    @model_validator(mode="after")
    def validate_payload_consistency(self):
        for vascello_key, assegnazioni in self.assegnazioni_per_vascello.items():
            if vascello_key not in self.mmsi_per_vascello:
                raise ValueError(f"MMSI mancante per vascello '{vascello_key}'")

            mmsi = self.mmsi_per_vascello[vascello_key]
            if not (mmsi.isdigit() and len(mmsi) == 9):
                raise ValueError(f"MMSI non valido per vascello '{vascello_key}': '{mmsi}'")

            for assegnazione in assegnazioni:
                if assegnazione.vascello_id != vascello_key:
                    raise ValueError(
                        f"vascello_id incoerente: bucket '{vascello_key}', assegnazione '{assegnazione.vascello_id}'"
                    )
                if assegnazione.piano_id != self.piano.id:
                    raise ValueError(
                        f"piano_id incoerente per assegnazione '{assegnazione.id}': '{assegnazione.piano_id}' != '{self.piano.id}'"
                    )
                if assegnazione.percorso_id != assegnazione.percorso.id:
                    raise ValueError(
                        f"percorso_id incoerente per assegnazione '{assegnazione.id}'"
                    )
                if assegnazione.id_corsa != assegnazione.corsa.id:
                    raise ValueError(
                        f"id_corsa incoerente per assegnazione '{assegnazione.id}'"
                    )
                if assegnazione.percorso.id_corsa != assegnazione.id_corsa:
                    raise ValueError(
                        f"percorso.id_corsa incoerente per assegnazione '{assegnazione.id}'"
                    )
                if assegnazione.percorso.vascello_id != vascello_key:
                    raise ValueError(
                        f"percorso.vascello_id incoerente per assegnazione '{assegnazione.id}'"
                    )

                stato = assegnazione.stato_esecuzione
                if stato == "COMPLETATA" and assegnazione.orario_completamento is None:
                    raise ValueError(
                        f"orario_completamento obbligatorio se stato=COMPLETATA (assegnazione '{assegnazione.id}')"
                    )
                if stato == "IN_CORSO" and assegnazione.orario_completamento is None:
                    raise ValueError(
                        f"orario_completamento richiesto come ETA corrente per stato=IN_CORSO (assegnazione '{assegnazione.id}')"
                    )

        return self


class IndicatoriGlobaliOutput(BaseModel):
    LateCount: int
    CriticalCount: int
    TotalDelay: float
    MaxDelay: float


class ReplanningCheckResponse(BaseModel):
    indicatori_globali: IndicatoriGlobaliOutput
    trigger: bool
    motivo: Optional[str] = None
    cooldown_attivo: bool
    freeze_window_minuti: int


def parse_datetime(value: Any) -> Optional[datetime]:
    def _to_rome_timezone(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ROME_TZ)
        return dt.astimezone(ROME_TZ)

    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_rome_timezone(value)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=ROME_TZ)
        except (OSError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return _to_rome_timezone(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


async def fetch_latest_delta_eta_map(target_mmsi: List[str], timeout_seconds: float = 5.0) -> Dict[str, float]:
    """Legge i messaggi già presenti su KAFKA_TOPIC_ANALYTICS e ritorna l'ultimo delta_min per MMSI richiesti."""
    from aiokafka import AIOKafkaConsumer
    import json

    if not target_mmsi:
        return {}

    latest: Dict[str, Tuple[float, float]] = {}
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC_ANALYTICS,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=None,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")) if m else None,
    )

    try:
        await consumer.start()
        await asyncio.sleep(0.2)
        end_time = asyncio.get_event_loop().time() + timeout_seconds

        while asyncio.get_event_loop().time() < end_time:
            try:
                batch = await asyncio.wait_for(
                    consumer.getmany(timeout_ms=800, max_records=200),
                    timeout=1.5,
                )
            except asyncio.TimeoutError:
                break

            if not batch:
                break

            for tp, records in batch.items():
                for record in records:
                    value = record.value or {}
                    mmsi = value.get("mmsi")
                    if mmsi not in target_mmsi:
                        continue
                    if value.get("type") != "delta_eta":
                        continue
                    delta = value.get("delta_min")
                    if delta is None:
                        continue
                    kafka_ts = record.timestamp or 0
                    stored = latest.get(mmsi)
                    if stored is None or kafka_ts >= stored[1]:
                        latest[mmsi] = (float(delta), float(kafka_ts))
    except Exception as exc:  # pragma: no cover
        logger.exception("Errore lettura delta_eta", extra={"error": str(exc)})
    finally:
        try:
            await consumer.stop()
        except Exception:
            pass

    latest_delta = {mmsi: v[0] for mmsi, v in latest.items()}
    logger.info(
        "Lettura delta_eta completata",
        extra={
            "topic": KAFKA_TOPIC_ANALYTICS,
            "target_mmsi_count": len(target_mmsi),
            "delta_found_count": len(latest_delta),
        },
    )
    return latest_delta


def propagate_delay_per_nave(
    assegnazioni: List[Dict[str, Any]],
    mmsi: Optional[str],
    delta_eta_per_mmsi: Dict[str, float],
    now: datetime,
) -> List[Dict[str, Any]]:
    """Applica la logica di propagazione del ritardo descritta nelle specifiche."""

    if not assegnazioni:
        return []

    def get_corsa_id(a: Dict[str, Any]) -> Optional[str]:
        return a.get("id_corsa") or a.get("corsa_id") or (a.get("corsa") or {}).get("id")

    def get_stato(a: Dict[str, Any]) -> Optional[str]:
        return a.get("stato_esecuzione") or a.get("stato")

    def schedulato_partenza(a: Dict[str, Any], duration_min: float) -> datetime:
        sched = (
            parse_datetime(a.get("orario_partenza"))
            or parse_datetime(a.get("schedulato_partenza"))
            or parse_datetime((a.get("corsa") or {}).get("orario_partenza_schedulato"))
        )
        if sched:
            return sched
        arr = parse_datetime(a.get("orario_completamento"))
        if arr:
            return arr - timedelta(minutes=duration_min)
        return now

    def durata_minuti(a: Dict[str, Any]) -> float:
        percorso = a.get("percorso") or {}
        if percorso.get("tempo_percorrenza_min") is not None:
            return float(percorso.get("tempo_percorrenza_min"))
        return float(a.get("durata_min", 60))

    ordered = sorted(
        assegnazioni,
        key=lambda a: schedulato_partenza(a, durata_minuti(a)),
    )

    preds: List[Dict[str, Any]] = []
    delta_eta = delta_eta_per_mmsi.get(mmsi) if mmsi else None

    first_idx = 0
    while first_idx < len(ordered) and get_stato(ordered[first_idx]) == "COMPLETATA":
        first_idx += 1
    if first_idx >= len(ordered):
        return preds

    ready_time_baseline = now
    for idx, a in enumerate(ordered):
        if idx >= first_idx:
            break
        duration = durata_minuti(a)
        deadhead = float(a.get("deadhead_min", 0))
        sched_arr = parse_datetime(a.get("orario_completamento"))
        if not sched_arr:
            sched_arr = schedulato_partenza(a, duration) + timedelta(minutes=duration)
        ready_time_baseline = max(ready_time_baseline, sched_arr + timedelta(minutes=deadhead))

    for idx, a in enumerate(ordered):
        if idx < first_idx:
            continue
        duration = durata_minuti(a)
        S_dep = schedulato_partenza(a, duration)
        deadhead = float(a.get("deadhead_min", 0))
        sched_arr = parse_datetime(a.get("orario_completamento"))
        if not sched_arr:
            sched_arr = S_dep + timedelta(minutes=duration)

        if idx == first_idx:
            if get_stato(a) == "IN_CORSO" and delta_eta is not None:
                Pred_dep = S_dep
                Pred_arr = sched_arr + timedelta(minutes=delta_eta)
            else:
                ready_time = max(ready_time_baseline, parse_datetime(a.get("ready_time")) or now)
                Pred_dep = max(S_dep, ready_time)
                Pred_arr = Pred_dep + timedelta(minutes=duration)
        else:
            prev = preds[-1]
            earliest_dep = prev["Pred_arr"] + timedelta(minutes=prev["Deadhead_min"])
            Pred_dep = max(S_dep, earliest_dep)
            Pred_arr = Pred_dep + timedelta(minutes=duration)

        delay_arr = (Pred_arr - sched_arr).total_seconds() / 60.0
        preds.append(
            {
                "corsa_id": get_corsa_id(a),
                "stato": get_stato(a),
                "Sched_dep": S_dep,
                "Sched_arr": sched_arr,
                "Pred_dep": Pred_dep,
                "Pred_arr": Pred_arr,
                "Deadhead_min": deadhead,
                "Durata_min": duration,
                "Delay_arr": delay_arr,
            }
        )

    return preds


def calcola_indicatori_globali(
    predizioni_per_nave: Dict[str, List[Dict[str, Any]]],
    now: datetime,
    H_minuti: int,
    theta: float,
    Theta: float,
    freeze_window_minuti: int = 0,
) -> Dict[str, float]:
    H = now + timedelta(minutes=H_minuti)
    freeze_end = now + timedelta(minutes=freeze_window_minuti)
    late_count = 0
    critical_count = 0
    total_delay = 0.0
    max_delay = 0.0

    for preds in predizioni_per_nave.values():
        for p in preds:
            arr = p["Pred_arr"]
            delay = p["Delay_arr"]
            if arr and now <= arr <= H:
                pred_dep = p.get("Pred_dep")
                in_freeze = bool(freeze_window_minuti > 0 and pred_dep and pred_dep <= freeze_end)
                if in_freeze and delay <= Theta:
                    continue
                if delay > theta:
                    late_count += 1
                if delay > Theta:
                    critical_count += 1
                if delay > 0:
                    total_delay += delay
                if delay > max_delay:
                    max_delay = delay

    return {
        "LateCount": late_count,
        "CriticalCount": critical_count,
        "TotalDelay": total_delay,
        "MaxDelay": max_delay,
    }


def check_replanning_trigger(
    indicatori: Dict[str, float],
    M: int,
    M_c: int,
    D_tot_max: float,
    D_max_max: float,
) -> Tuple[bool, Optional[str]]:
    if indicatori["LateCount"] > M:
        return True, "LateCount > M"
    if indicatori["CriticalCount"] > M_c:
        return True, "CriticalCount > M_c"
    if indicatori["TotalDelay"] > D_tot_max:
        return True, "TotalDelay > D_tot_max"
    if indicatori["MaxDelay"] > D_max_max:
        return True, "MaxDelay > D_max_max"
    return False, None


async def apply_cooldown_guard(
    trigger: bool,
    motivo: Optional[str],
    now: datetime,
    cooldown_minuti: int,
) -> Tuple[bool, Optional[str], bool]:
    global last_replanning_trigger_at

    if cooldown_minuti <= 0:
        return trigger, motivo, False

    async with replanning_state_lock:
        if not trigger:
            return False, motivo, False

        if last_replanning_trigger_at is None:
            last_replanning_trigger_at = now
            return True, motivo, False

        delta = now - last_replanning_trigger_at
        cooldown = timedelta(minutes=cooldown_minuti)
        if delta < cooldown:
            return False, "COOLDOWN_ATTIVO", True

        last_replanning_trigger_at = now
        return True, motivo, False


async def publish_replanning_notification(motivo: Optional[str], piano_id: str) -> None:
    payload = {
        "msg_type": "replanning",
        "piano_id": piano_id,
        "motivo": motivo or "TRIGGER_REPLANNING",
    }
    try:
        await broker.publish(payload, KAFKA_TOPIC_NOTIFICATIONS)
        logger.info(
            "Notifica replanning pubblicata",
            extra={
                "topic": KAFKA_TOPIC_NOTIFICATIONS,
                "piano_id": payload["piano_id"],
                "motivo": payload["motivo"],
            },
        )
    except Exception as exc:  # pragma: no cover
        logger.exception(
            "Errore pubblicazione notifica replanning",
            extra={
                "topic": KAFKA_TOPIC_NOTIFICATIONS,
                "piano_id": payload["piano_id"],
                "error": str(exc),
            },
        )


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/replanning/check", response_model=ReplanningCheckResponse)
async def check_replanning(data: ReplanningCheckInput):
    start_time = time.perf_counter()
    now = datetime.now(ROME_TZ)
    theta = REPLANNING_THETA_MIN
    Theta = REPLANNING_THETA_CRITICAL_MIN
    M = REPLANNING_MAX_LATE
    M_c = REPLANNING_MAX_CRITICAL
    D_tot_max = REPLANNING_TOTAL_DELAY_MAX
    D_max_max = REPLANNING_SINGLE_DELAY_MAX
    H_minuti = REPLANNING_HORIZON_MINUTES
    freeze_window_minuti = REPLANNING_FREEZE_WINDOW_MINUTES

    total_assegnazioni = sum(len(x) for x in data.assegnazioni_per_vascello.values())
    logger.info(
        "Richiesta replanning ricevuta",
        extra={
            "piano_id": data.piano.id,
            "vascelli_count": len(data.assegnazioni_per_vascello),
            "assegnazioni_count": total_assegnazioni,
        },
    )

    assegnazioni_per_vascello = {
        vascello_id: [assegnazione.model_dump() for assegnazione in assegnazioni]
        for vascello_id, assegnazioni in data.assegnazioni_per_vascello.items()
    }

    target_mmsi = []
    for vascello_id, assegnazioni in assegnazioni_per_vascello.items():
        has_in_corso = any(((a.get("stato_esecuzione") or a.get("stato")) == "IN_CORSO") for a in assegnazioni)
        if has_in_corso:
            mmsi = data.mmsi_per_vascello.get(vascello_id)
            if mmsi:
                target_mmsi.append(mmsi)

    logger.info(
        "Selezione MMSI per delta_eta",
        extra={
            "mmsi_target_count": len(target_mmsi),
        },
    )

    delta_eta_map = await fetch_latest_delta_eta_map(target_mmsi)

    predizioni_per_nave: Dict[str, List[Dict[str, Any]]] = {}
    for vascello_id, assegnazioni in assegnazioni_per_vascello.items():
        mmsi = data.mmsi_per_vascello.get(vascello_id)
        predizioni_per_nave[vascello_id] = propagate_delay_per_nave(
            assegnazioni,
            mmsi,
            delta_eta_map,
            now,
        )
    print(predizioni_per_nave)

    indicatori = calcola_indicatori_globali(predizioni_per_nave, now, H_minuti, theta, Theta)
    indicatori_trigger = calcola_indicatori_globali(
        predizioni_per_nave,
        now,
        H_minuti,
        theta,
        Theta,
        freeze_window_minuti=freeze_window_minuti,
    )

    trigger, motivo = check_replanning_trigger(indicatori_trigger, M, M_c, D_tot_max, D_max_max)
    trigger, motivo, cooldown_attivo = await apply_cooldown_guard(
        trigger,
        motivo,
        now,
        REPLANNING_COOLDOWN_MINUTES,
    )

    if trigger:
        await publish_replanning_notification(motivo, data.piano.id)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(
        "Valutazione replanning completata",
        extra={
            "piano_id": data.piano.id,
            "trigger": trigger,
            "motivo": motivo,
            "cooldown_attivo": cooldown_attivo,
            "freeze_window_minuti": freeze_window_minuti,
            "elapsed_ms": elapsed_ms,
        },
    )

    return {
        "indicatori_globali": indicatori,
        "trigger": trigger,
        "motivo": motivo,
        "cooldown_attivo": cooldown_attivo,
        "freeze_window_minuti": freeze_window_minuti,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT)
