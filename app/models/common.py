from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ServiceConfig(BaseModel):
    """Configurazione runtime del servizio API Gateway."""
    cache_delta_minutes: int = Field(
        120,
        description=(
            "Numero di minuti per cui il risultato di un'ottimizzazione weather routing è "
            "considerato valido in cache. Se l'ultima ottimizzazione è avvenuta entro questa "
            "finestra, il risultato viene restituito dalla cache senza ricalcolo, "
            "risparmiando latenza e risorse computazionali."
        ),
        ge=1,
        le=1440,
        example=120
    )
    replanning_check_interval_seconds: int = Field(
        300,
        description=(
            "Cadenza in secondi del job periodico che verifica automaticamente se il piano "
            "operativo attivo necessita di replanning. A ogni ciclo vengono valutati ritardi, "
            "deviazioni e tutte le soglie configurate. Valori bassi aumentano la reattività "
            "ma incrementano il carico computazionale sul servizio di replanning."
        ),
        ge=5,
        le=86400,
        example=300
    )
    replanning_theta_min: float = Field(
        10.0,
        description=(
            "Soglia di ritardo minimo in minuti (θ_min). Una corsa è conteggiata come "
            "'in ritardo' quando il suo ritardo supera questo valore. Il contatore M "
            "(confrontato con max_late) viene incrementato per ogni corsa con ritardo "
            "> theta_min nell'orizzonte di analisi."
        ),
        ge=0,
    )
    replanning_theta_critical_min: float = Field(
        30.0,
        description=(
            "Soglia di ritardo critico in minuti (θ_critical), necessariamente più alta di "
            "theta_min. Una corsa è classificata come 'in ritardo critico' quando supera "
            "questo valore. Il contatore M_c (confrontato con max_critical) viene "
            "incrementato per ogni corsa con ritardo > theta_critical_min."
        ),
        ge=0,
    )
    replanning_max_late: int = Field(
        2,
        description=(
            "Numero massimo tollerato di corse in ritardo (M, ritardo > theta_min) "
            "nell'orizzonte temporale di analisi. Se il conteggio M supera questo valore "
            "il trigger di replanning viene attivato e la notifica pubblicata su Kafka."
        ),
        ge=0,
    )
    replanning_max_critical: int = Field(
        1,
        description=(
            "Numero massimo tollerato di corse in ritardo critico (M_c, ritardo > "
            "theta_critical_min) nell'orizzonte temporale. Anche una sola corsa critica "
            "oltre questa soglia attiva immediatamente il replanning, indipendentemente "
            "dal valore di max_late."
        ),
        ge=0,
    )
    replanning_total_delay_max: float = Field(
        60.0,
        description=(
            "Ritardo cumulativo massimo tollerato in minuti (D_tot_max): somma di tutti i "
            "ritardi delle corse nell'orizzonte di analisi. Superato questo limite il "
            "replanning viene attivato indipendentemente dai contatori M e M_c."
        ),
        ge=0,
    )
    replanning_single_delay_max: float = Field(
        40.0,
        description=(
            "Ritardo massimo tollerato per una singola corsa in minuti (D_max). Se anche "
            "solo una corsa supera questo valore il trigger di replanning scatta "
            "immediatamente, indipendentemente dagli altri parametri e contatori."
        ),
        ge=0,
    )
    replanning_horizon_minutes: int = Field(
        120,
        description=(
            "Ampiezza in minuti della finestra temporale futura analizzata a ogni check. "
            "Solo le corse con partenza o arrivo previsti entro questo orizzonte vengono "
            "considerate nel calcolo dei ritardi e nei contatori M, M_c, D_tot e D_max."
        ),
        ge=1,
    )
    replanning_cooldown_minutes: int = Field(
        30,
        description=(
            "Periodo di silenzio in minuti dopo un trigger di replanning, durante il quale "
            "nuovi trigger non vengono generati né notificati su Kafka. Previene oscillazioni "
            "e notifiche ripetute causate dallo stesso evento di ritardo persistente."
        ),
        ge=0,
    )
    replanning_freeze_window_minutes: int = Field(
        15,
        description=(
            "Finestra temporale in minuti prima della partenza di una corsa durante la quale "
            "le modifiche operative sono bloccate (freeze operativo). Le corse con partenza "
            "imminente entro questa finestra vengono escluse dal replanning per evitare "
            "interferenze con operazioni già avviate o in fase di boarding."
        ),
        ge=0,
    )


class ServiceConfigUpdate(BaseModel):
    """Schema per l'aggiornamento parziale della configurazione runtime del servizio."""
    cache_delta_minutes: Optional[int] = Field(
        None,
        description=(
            "Nuova durata in minuti della cache dei risultati di ottimizzazione weather routing. "
            "Se omesso il valore corrente rimane invariato."
        ),
        ge=1,
        le=1440
    )
    replanning_check_interval_seconds: Optional[int] = Field(
        None,
        description=(
            "Nuova cadenza in secondi del job periodico di check replanning. "
            "La modifica rischedula immediatamente il job con il nuovo intervallo. "
            "Se omesso il valore corrente rimane invariato."
        ),
        ge=5,
        le=86400
    )
    replanning_theta_min: Optional[float] = Field(
        None,
        description=(
            "Nuova soglia di ritardo minimo in minuti (θ_min). "
            "Abbassare il valore rende il sistema più sensibile ai ritardi lievi; "
            "alzarlo ignora piccoli scostamenti dal piano. Se omesso rimane invariato."
        ),
        ge=0,
    )
    replanning_theta_critical_min: Optional[float] = Field(
        None,
        description=(
            "Nuova soglia di ritardo critico in minuti (θ_critical). "
            "Deve essere impostata a un valore maggiore di theta_min per una distinzione "
            "significativa tra ritardo normale e critico. Se omesso rimane invariato."
        ),
        ge=0,
    )
    replanning_max_late: Optional[int] = Field(
        None,
        description=(
            "Nuovo numero massimo tollerato di corse in ritardo (M > theta_min). "
            "Ridurlo aumenta la sensibilità del sistema; portarlo a 0 attiva il replanning "
            "al primo ritardo. Se omesso rimane invariato."
        ),
        ge=0,
    )
    replanning_max_critical: Optional[int] = Field(
        None,
        description=(
            "Nuovo numero massimo tollerato di corse in ritardo critico (M_c > theta_critical_min). "
            "Un valore di 0 attiva il replanning alla prima corsa critica rilevata. "
            "Se omesso rimane invariato."
        ),
        ge=0,
    )
    replanning_total_delay_max: Optional[float] = Field(
        None,
        description=(
            "Nuovo ritardo cumulativo massimo tollerato in minuti (D_tot_max). "
            "Ridurlo rende il sistema più reattivo a ritardi distribuiti su più corse. "
            "Se omesso rimane invariato."
        ),
        ge=0,
    )
    replanning_single_delay_max: Optional[float] = Field(
        None,
        description=(
            "Nuovo ritardo massimo tollerato per una singola corsa in minuti (D_max). "
            "Ridurlo protegge le corse singole con grandi ritardi anche se il totale è basso. "
            "Se omesso rimane invariato."
        ),
        ge=0,
    )
    replanning_horizon_minutes: Optional[int] = Field(
        None,
        description=(
            "Nuova ampiezza in minuti della finestra temporale futura analizzata. "
            "Un orizzonte più lungo include più corse nell'analisi ma può diluire i segnali "
            "di ritardo imminente. Se omesso rimane invariato."
        ),
        ge=1,
    )
    replanning_cooldown_minutes: Optional[int] = Field(
        None,
        description=(
            "Nuovo periodo di silenzio in minuti dopo un trigger. "
            "Un valore di 0 disabilita il cooldown: ogni ciclo può generare un nuovo trigger. "
            "Se omesso rimane invariato."
        ),
        ge=0,
    )
    replanning_freeze_window_minutes: Optional[int] = Field(
        None,
        description=(
            "Nuova finestra di freeze operativo in minuti prima della partenza. "
            "Un valore di 0 disabilita il freeze: anche le corse imminenti vengono incluse "
            "nell'analisi di replanning. Se omesso rimane invariato."
        ),
        ge=0,
    )


class OttimizzatoreInput(BaseModel):
    """Parametri per l'ottimizzazione weather routing di una singola coppia vascello-corsa."""
    corsa_id: str = Field(..., description="UUID della corsa da ottimizzare")
    vascello_id: str = Field(..., description="UUID del vascello da utilizzare")
    eps_time: float = Field(
        5,
        description="Tolleranza temporale in minuti per il vincolo orario di arrivo",
        ge=0,
        example=5
    )
    fake_data: bool = Field(
        True,
        description="Se True, utilizza dati meteo simulati invece di dati reali"
    )
    ve_min: float = Field(
        0.1,
        description="Velocità minima consentita in nodi",
        ge=0.01,
        example=0.1
    )
    tolerance: float = Field(
        1,
        description="Tolleranza dell'algoritmo di ottimizzazione",
        ge=0.1,
        example=1
    )
    scenario_id: int | None = Field(
        None,
        description=(
            "ID di uno scenario meteo what-if salvato nel weather_service. "
            "Se specificato, i dati Copernicus vengono alterati secondo lo scenario "
            "prima dell'ottimizzazione. Usare GET /weather/scenarios per vedere "
            "gli scenari disponibili o POST /weather/scenarios per crearne uno."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "corsa_id": "550e8400-e29b-41d4-a716-446655440000",
                    "vascello_id": "550e8400-e29b-41d4-a716-446655440001",
                    "eps_time": 5,
                    "fake_data": True,
                    "ve_min": 0.1,
                    "tolerance": 1
                }
            ]
        }
    }


class OttimizzatoreBatchInput(BaseModel):
    """Input batch per l'ottimizzazione di multiple coppie vascello-corsa."""
    items: List[OttimizzatoreInput] = Field(
        ...,
        description="Lista di richieste di ottimizzazione da processare in batch"
    )


class OttimizzatoreSingleResponse(BaseModel):
    """Risultato ottimizzazione per una singola coppia vascello-corsa."""
    status: str = Field(..., description="Esito: 'success' o 'error'")
    corsa_id: str = Field(..., description="UUID della corsa")
    vascello_id: str = Field(..., description="UUID del vascello")
    percorsi_inseriti: List[str] = Field(..., description="Lista UUID percorsi ottimali inseriti")


class OttimizzatoreResponse(BaseModel):
    """Risposta batch dell'ottimizzatore weather routing."""
    results: List[OttimizzatoreSingleResponse] = Field(
        ...,
        description="Lista risultati per ogni coppia vascello-corsa"
    )


class RiposizionamentoInput(BaseModel):
    """Parametri per la stima di un riposizionamento a vuoto."""
    porto_partenza_id: str = Field(..., description="UUID del porto di partenza")
    porto_destinazione_id: str = Field(..., description="UUID del porto di destinazione")
    datetime_partenza: datetime = Field(
        ...,
        description="Data/ora di partenza prevista (ISO 8601)",
        example="2025-01-30T08:00:00"
    )
    vascello_id: str = Field(..., description="UUID del vascello da riposizionare")
    fake_data: bool = Field(True, description="Se True, usa dati meteo simulati")
    ve_min: float = Field(0.1, description="Velocità minima in nodi", ge=0.01)
    tolerance: float = Field(1, description="Tolleranza algoritmo", ge=0.1)
    graph_cache_ttl_minutes: Optional[int] = Field(
        None,
        description="TTL cache in minuti per snap temporale richiesta (0 o None disattiva)",
        ge=0
    )
    scenario_id: int | None = Field(
        None,
        description=(
            "ID di uno scenario meteo what-if salvato nel weather_service. "
            "Se specificato, i dati Copernicus vengono alterati secondo lo scenario "
            "prima del calcolo del riposizionamento. Usare GET /weather/scenarios per vedere "
            "gli scenari disponibili o POST /weather/scenarios per crearne uno."
        ),
    )

class RiposizionamentoBatchInput(BaseModel):
    """Input batch per stime riposizionamento multiple."""
    items: List[RiposizionamentoInput] = Field(
        ...,
        description="Lista richieste di riposizionamento"
    )


class RiposizionamentoSingleResponse(BaseModel):
    """Risultato stima riposizionamento singolo."""
    porto_partenza_id: str = Field(..., description="UUID porto partenza")
    porto_destinazione_id: str = Field(..., description="UUID porto destinazione")
    vascello_id: str = Field(..., description="UUID vascello")
    tempo_riposizionamento: float = Field(..., description="Tempo stimato in minuti")
    consumo_riposizionamento: float = Field(..., description="Consumo carburante stimato in litri")


class RiposizionamentoResponse(BaseModel):
    """Risposta batch per stime riposizionamento."""
    results: List[RiposizionamentoSingleResponse] = Field(
        ...,
        description="Lista risultati per ogni riposizionamento richiesto"
    )


class AssignmentRequest(BaseModel):
    """Richiesta per il calcolo della pianificazione ottimale flotte."""
    start: datetime = Field(
        ...,
        description="Inizio finestra temporale di pianificazione (ISO 8601)",
        example="2025-01-30T06:00:00"
    )
    end: datetime = Field(
        ...,
        description="Fine finestra temporale di pianificazione (ISO 8601)",
        example="2025-01-30T22:00:00"
    )
    vessels: List[str] = Field(
        ...,
        description="Lista UUID vascelli disponibili per l'assegnazione"
    )
    eps_time: int = Field(
        ...,
        description="Tolleranza temporale in minuti",
        ge=0,
        example=5
    )
    fake_data: bool = Field(
        ...,
        description="Se True, utilizza dati meteo simulati"
    )
    scenario_id: int | None = Field(
        None,
        description=(
            "ID di uno scenario meteo what-if salvato nel weather_service. "
            "Se specificato, i dati Copernicus vengono alterati secondo lo scenario "
            "per tutte le ottimizzazioni della pianificazione. Usare GET /weather/scenarios "
            "per vedere gli scenari disponibili o POST /weather/scenarios per crearne uno."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "start": "2025-01-30T06:00:00",
                    "end": "2025-01-30T22:00:00",
                    "vessels": ["uuid-vascello-1", "uuid-vascello-2"],
                    "eps_time": 5,
                    "fake_data": True
                }
            ]
        }
    }


class VesselKPI(BaseModel):
    """KPI di un vascello per una specifica assegnazione."""
    nome_vascello: str = Field(..., description="Nome del vascello")
    consumo: float = Field(..., description="Consumo carburante stimato (litri)")
    comfort: float = Field(..., description="Indice di comfort navigazione (0-100)")
    tempo_percorrenza_sec: float = Field(..., description="Tempo percorrenza in secondi")
    orario_arrivo_previsto: str = Field(..., description="Orario arrivo stimato (ISO 8601)")
    capacita_passeggeri: Optional[int] = Field(None, description="Capacità passeggeri del vascello")


class RouteAssignment(BaseModel):
    """Assegnazione ottimale per una corsa con KPI per ogni vascello candidato."""
    nome_corsa: str = Field(..., description="Nome della corsa")
    porto_partenza: str = Field(..., description="Nome porto partenza")
    porto_arrivo: str = Field(..., description="Nome porto arrivo")
    porto_partenza_id: str = Field(..., description="UUID porto partenza")
    porto_arrivo_id: str = Field(..., description="UUID porto arrivo")
    orario_partenza_schedulato: str = Field(..., description="Orario partenza schedulato")
    passeggeri_previsti: Optional[List[float]] = Field(
        None,
        description="Previsione passeggeri [stimati, ci_min, ci_max]"
    )
    KPI_assegnazione: Dict[str, VesselKPI] = Field(
        ...,
        description="Mappa vascello_id → KPI per ranking assegnazione"
    )


class SimVesselInput(BaseModel):
    """Input per la simulazione di un singolo vascello."""
    assegnazione_id: str = Field(
        ...,
        description="UUID dell'assegnazione da simulare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    lat_start: Optional[float] = Field(
        None,
        description="Latitudine iniziale custom (se None, usa porto partenza)",
        ge=-90,
        le=90
    )
    lon_start: Optional[float] = Field(
        None,
        description="Longitudine iniziale custom (se None, usa porto partenza)",
        ge=-180,
        le=180
    )


class SimulationRequest(BaseModel):
    """Richiesta per il simulatore fisico di navigazione."""
    timestep: float = Field(
        0.1,
        description="Passo temporale simulazione in secondi",
        ge=0.01,
        le=10
    )
    vessels: List[dict] = Field(..., description="Lista configurazioni vascelli da simulare")


class SimulationBuildInput(BaseModel):
    """Input per costruzione ed esecuzione simulazione batch."""
    elementi: List[SimVesselInput] = Field(
        ...,
        description="Lista elementi da simulare con coordinate opzionali"
    )
    sim_speed_factor: Optional[float] = Field(
        None,
        description="Fattore di accelerazione simulazione (se None, usa valore configurazione). Aggiorna anche la configurazione globale.",
        ge=0.1,
        le=100.0,
        example=1.0
    )


class CheckValiditaInput(BaseModel):
    """Input per verifica validità sequenziale tra due percorsi."""
    percorso_1_id: str = Field(
        ...,
        description="UUID del primo percorso",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    percorso_2_id: str = Field(
        ...,
        description="UUID del secondo percorso",
        example="550e8400-e29b-41d4-a716-446655440001"
    )


class CheckValiditaResponse(BaseModel):
    """Risultato verifica validità sequenziale percorsi."""
    valido: bool = Field(..., description="True se i percorsi possono essere eseguiti in sequenza")
    percorso_1: Dict[str, Any] = Field(..., description="Dettagli primo percorso (ordinato per orario)")
    percorso_2: Dict[str, Any] = Field(..., description="Dettagli secondo percorso")
    messaggio: str = Field(..., description="Descrizione esito validazione")


class PercorsiCompatibiliInput(BaseModel):
    """Input per verifica compatibilità percorsi rispetto a una corsa."""
    corsa_id: str = Field(
        ...,
        description="UUID della corsa di riferimento",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    percorsi_id: List[str] = Field(
        ...,
        description="Lista UUID dei percorsi già assegnati dall'utente",
        example=["550e8400-e29b-41d4-a716-446655440001", "550e8400-e29b-41d4-a716-446655440002"]
    )


class PercorsoCompatibile(BaseModel):
    """Dettaglio di un percorso compatibile."""
    # Campi percorso
    percorso_id: str = Field(..., description="UUID del percorso")
    tempo_percorrenza_min: Optional[Any] = Field(None, description="Tempo percorrenza in minuti")
    consumo: Optional[float] = Field(None, description="Consumo carburante (litri)")
    comfort: Optional[float] = Field(None, description="Indice comfort (0-100)")
    # Campi vascello
    vascello_id: Optional[str] = Field(None, description="UUID del vascello")
    vascello_nome: Optional[str] = Field(None, description="Nome del vascello")
    # Campi corsa
    orario_partenza_schedulato: Optional[str] = Field(None, description="Orario partenza schedulato")
    orario_arrivo_max: Optional[str] = Field(None, description="Orario arrivo massimo")


class PercorsiCompatibiliResponse(BaseModel):
    """Risposta con i percorsi della corsa compatibili con quelli già assegnati."""
    corsa_id: str = Field(..., description="UUID della corsa di riferimento")
    percorsi_compatibili: List[PercorsoCompatibile] = Field(
        ...,
        description="Lista percorsi della corsa compatibili con tutti i percorsi già assegnati"
    )


# ========================================
# Scheduling Models
# ========================================

class SchedulingRouteInput(BaseModel):
    """Route input for scheduling optimization."""
    route_id: str = Field(..., description="UUID del percorso")
    corsa_id: str = Field(..., description="UUID della corsa")
    corsa_name: Optional[str] = Field(None, description="Nome della corsa")
    vessel_id: str = Field(..., description="UUID del vascello")
    vessel_name: Optional[str] = Field(None, description="Nome del vascello")
    capacity: float = Field(..., description="Capacità passeggeri del vascello", ge=0)
    origin: str = Field(..., description="UUID del porto di partenza")
    destination: str = Field(..., description="UUID del porto di arrivo")
    start_dt: str = Field(..., description="Orario partenza (ISO 8601)", example="2026-02-05T08:00:00")
    end_dt: str = Field(..., description="Orario arrivo (ISO 8601)", example="2026-02-05T09:00:00")
    consumo: float = Field(..., description="Consumo carburante", ge=0)
    comfort: float = Field(0.0, description="Indice di comfort", ge=0, le=100)
    pax_min: float = Field(0, description="Previsione passeggeri minima", ge=0)
    pax_max: float = Field(0, description="Previsione passeggeri massima", ge=0)


class SchedulingVesselInput(BaseModel):
    """Vessel input for scheduling optimization."""
    vessel_id: str = Field(..., description="UUID del vascello")
    name: Optional[str] = Field(None, description="Nome del vascello")
    capacity: float = Field(..., description="Capacità passeggeri", ge=0)


class SchedulingInput(BaseModel):
    """Input for scheduling optimization."""
    routes: List[SchedulingRouteInput] = Field(
        ...,
        description="Lista dei percorsi da schedulare"
    )
    vessels: List[SchedulingVesselInput] = Field(
        ...,
        description="Lista dei vascelli disponibili"
    )
    max_solutions: int = Field(
        5,
        description="Numero massimo di soluzioni Pareto-ottimali da restituire",
        ge=1,
        le=100
    )
    include_details: bool = Field(
        True,
        description="Se True, include attività dettagliate (riposizionamenti, attese)")
class PercorsoAssegnazioneItem(BaseModel):
    """Singolo percorso con flag virtuale per creazione assegnazioni bulk."""
    percorso_id: str = Field(
        ...,
        description="UUID del percorso da assegnare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    virtuale: bool = Field(
        ...,
        description="True se l'assegnazione è virtuale (simulazione automatica schedulata)",
        example=False
    )


class CreaAssegnazioniBulkInput(BaseModel):
    """Input per la creazione bulk di assegnazioni con scheduling simulazioni."""
    piano_id: str = Field(
        ...,
        description="UUID del piano operativo di riferimento",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    percorsi: List[PercorsoAssegnazioneItem] = Field(
        ...,
        description="Lista percorsi con flag virtuale per ogni assegnazione"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "piano_id": "550e8400-e29b-41d4-a716-446655440000",
                    "percorsi": [
                        {"percorso_id": "550e8400-e29b-41d4-a716-446655440001", "virtuale": False},
                        {"percorso_id": "550e8400-e29b-41d4-a716-446655440002", "virtuale": True}
                    ]
                }
            ]
        }
    }


class SchedulingActivity(BaseModel):
    """Single activity in a schedule (trip, repositioning, or wait)."""
    solution_id: int = Field(..., description="ID della soluzione")
    vessel_id: str = Field(..., description="UUID del vascello")
    vessel_name: Optional[str] = Field(None, description="Nome del vascello")
    type: str = Field(..., description="Tipo attività: TRIP, REPOSITION, WAIT")
    detail: Optional[str] = Field(None, description="Dettaglio attività")
    route_id: Optional[str] = Field(None, description="UUID del percorso (solo per TRIP)")
    corsa_id: Optional[str] = Field(None, description="UUID della corsa (solo per TRIP)")
    origin: str = Field(..., description="Porto/località di partenza")
    destination: str = Field(..., description="Porto/località di arrivo")
    start_dt: str = Field(..., description="Orario inizio (ISO 8601)")
    end_dt: str = Field(..., description="Orario fine (ISO 8601)")
    duration_min: float = Field(..., description="Durata in minuti")
    cost: float = Field(..., description="Costo/consumo dell'attività")


class SchedulingSolutionRoute(BaseModel):
    """Route in a scheduling solution."""
    route_id: str = Field(..., description="UUID del percorso")
    corsa_id: str = Field(..., description="UUID della corsa")
    corsa_name: Optional[str] = Field(None, description="Nome della corsa")
    vessel_id: str = Field(..., description="UUID del vascello")
    vessel_name: Optional[str] = Field(None, description="Nome del vascello")
    capacity: float = Field(..., description="Capacità passeggeri")
    origin: str = Field(..., description="UUID porto partenza")
    destination: str = Field(..., description="UUID porto arrivo")
    start_dt: str = Field(..., description="Orario partenza (ISO 8601)")
    end_dt: str = Field(..., description="Orario arrivo (ISO 8601)")
    consumo: float = Field(..., description="Consumo carburante")
    comfort: float = Field(..., description="Indice comfort")
    pax_min: float = Field(..., description="Previsione passeggeri min")
    pax_max: float = Field(..., description="Previsione passeggeri max")


class SchedulingSolution(BaseModel):
    """Single Pareto-optimal scheduling solution."""
    solution_id: int = Field(..., description="ID della soluzione")
    cost: float = Field(..., description="Costo totale (consumo)")
    risk: float = Field(..., description="Rischio totale (probabilità sovraccarico)")
    plan: Dict[str, List[SchedulingSolutionRoute]] = Field(
        ...,
        description="Piano per vascello: vessel_id -> lista percorsi assegnati"
    )
    activities: Optional[List[SchedulingActivity]] = Field(
        None,
        description="Lista attività dettagliate (se include_details=True)"
    )


class SchedulingResponse(BaseModel):
    """Response from scheduling optimization."""
    status: str = Field(..., description="Stato: ok o error")
    solutions: List[SchedulingSolution] = Field(
        default=[],
        description="Lista soluzioni Pareto-ottimali ordinate per costo"
    )
    message: Optional[str] = Field(None, description="Messaggio aggiuntivo")


class SchedulingByDayInput(BaseModel):
    """Input for scheduling optimization by day."""
    giorno: str = Field(
        ...,
        description="Giorno da schedulare (formato YYYY-MM-DD)",
        example="2026-02-05"
    )
    solo_future: bool = Field(
        True,
        description="Se True, considera solo corse future rispetto all'orario attuale"
    )
    max_solutions: int = Field(
        5,
        description="Numero massimo di soluzioni Pareto-ottimali",
        ge=1,
        le=100
    )
    include_details: bool = Field(
        True,
        description="Se True, include attività dettagliate"
    )
    eps_time: float = Field(
        5,
        description="Tolleranza temporale per ottimizzazione percorsi",
        ge=0
    )
    fake_data: bool = Field(
        False,
        description="Se True, usa dati meteo simulati" )
class AssegnazioneBulkResult(BaseModel):
    """Risultato singola assegnazione creata nel bulk."""
    assegnazione_id: str = Field(..., description="UUID dell'assegnazione creata")
    percorso_id: str = Field(..., description="UUID del percorso")
    virtuale: bool = Field(..., description="Flag virtuale dell'assegnazione")


class CreaAssegnazioniBulkResponse(BaseModel):
    """Risposta per la creazione bulk di assegnazioni."""
    piano_id: str = Field(..., description="UUID del piano operativo")
    assegnazioni_create: int = Field(..., description="Numero di assegnazioni create")
    risultati: List[AssegnazioneBulkResult] = Field(
        ...,
        description="Dettaglio per ogni assegnazione creata"
    )


class SimulaPianoInput(BaseModel):
    """Input per la simulazione anticipata di un piano operativo."""
    piano_id: str = Field(
        ...,
        description="UUID del piano operativo da simulare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    delay_start_seconds: int = Field(
        5,
        description="Ritardo in secondi prima dell'avvio della prima simulazione",
        ge=0,
        le=3600,
        example=5
    )
    sim_speed_factor: Optional[float] = Field(
        None,
        description="Fattore di accelerazione simulazione (se None, usa valore configurazione). I delta temporali vengono scalati. Aggiorna anche la configurazione globale.",
        ge=0.1,
        le=100.0,
        example=1.0
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "piano_id": "550e8400-e29b-41d4-a716-446655440000",
                    "delay_start_seconds": 5,
                    "sim_speed_factor": 1.0
                }
            ]
        }
    }


class SimulazionePianoResult(BaseModel):
    """Risultato singola simulazione schedulata per il piano."""
    assegnazione_id: str = Field(..., description="UUID dell'assegnazione")
    orario_originale: str = Field(..., description="Orario partenza schedulato originale (ISO 8601)")
    orario_simulazione: str = Field(..., description="Orario schedulato per la simulazione (ISO 8601)")
    delta_from_first_seconds: int = Field(..., description="Delta in secondi rispetto alla prima partenza")
    job_id: str = Field(..., description="ID del job schedulato")


class SimulaPianoResponse(BaseModel):
    """Risposta per la simulazione anticipata di un piano operativo."""
    piano_id: str = Field(..., description="UUID del piano operativo")
    status: str = Field(..., description="Stato dell'operazione: 'ok' o 'error'")
    assegnazioni_virtuali_trovate: int = Field(..., description="Numero di assegnazioni virtuali trovate")
    simulazioni_schedulate: int = Field(..., description="Numero di simulazioni schedulate con successo")
    orario_base_simulazione: str = Field(..., description="Orario di base da cui partono le simulazioni (ISO 8601)")
    risultati: List[SimulazionePianoResult] = Field(
        ...,
        description="Dettaglio per ogni simulazione schedulata"
    )
    messaggio: Optional[str] = Field(None, description="Messaggio informativo o di errore")


# ========================================
# Variazione Percorso Models
# ========================================

class TipoVariazione(str):
    """Tipologie di variazione applicabili a un percorso."""
    GUASTO = "GUASTO"
    DEVIAZIONE = "DEVIAZIONE"


class VariazionePercorsoInput(BaseModel):
    """Input per applicare una variazione a un percorso esistente."""
    percorso_id: str = Field(
        ...,
        description="UUID del percorso da modificare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    tipo_variazione: str = Field(
        ...,
        description="Tipo di variazione: GUASTO (riduce vref di un waypoint casuale) o DEVIAZIONE (aggiunge waypoint intermedio)",
        example="GUASTO"
    )
    offset_deviazione_nm: float = Field(
        0.5,
        description="Offset in miglia nautiche per la deviazione (solo per DEVIAZIONE)",
        ge=0.01,
        le=10,
        example=0.5
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "percorso_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tipo_variazione": "GUASTO"
                },
                {
                    "percorso_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tipo_variazione": "DEVIAZIONE",
                    "offset_deviazione_nm": 0.5
                }
            ]
        }
    }


class VariazionePercorsoResponse(BaseModel):
    """Risposta per l'applicazione di una variazione a un percorso."""
    status: str = Field(..., description="Stato: 'ok' o 'error'")
    percorso_originale_id: str = Field(..., description="UUID del percorso originale")
    percorso_variato_id: str = Field(..., description="UUID del nuovo percorso creato con la variazione")
    tipo_variazione: str = Field(..., description="Tipo di variazione applicata")
    dettagli_variazione: Dict[str, Any] = Field(
        ...,
        description="Dettagli specifici della variazione applicata"
    )
    messaggio: Optional[str] = Field(None, description="Messaggio informativo")