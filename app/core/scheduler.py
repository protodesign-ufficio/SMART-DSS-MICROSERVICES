"""
Modulo per la gestione dello scheduler di job.
Utilizza APScheduler per schedulare simulazioni automatiche.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from app.core.config import OPERATIVO_SERVICE_URL, SERVICE_CONFIG

# Configurazione scheduler
jobstores = {
    'default': MemoryJobStore()
}

executors = {
    'default': ThreadPoolExecutor(20)
}

job_defaults = {
    'coalesce': False,
    'max_instances': 3
}

# Scheduler globale
scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone=ZoneInfo("Europe/Rome")
)

REPLANNING_JOB_ID = "periodic_replanning_check"
LAST_REPLANNING_STATUS = {
    "last_started_at": None,
    "last_finished_at": None,
    "last_success": None,
    "last_error": None,
    "last_result": None
}


def _run_periodic_replanning_job():
    """Job periodico che avvia i check di replanning."""
    from app.services.replanning_service import run_periodic_replanning_cycle

    now = datetime.now(ZoneInfo("Europe/Rome")).isoformat()
    LAST_REPLANNING_STATUS["last_started_at"] = now

    try:
        result = run_periodic_replanning_cycle()
        LAST_REPLANNING_STATUS["last_finished_at"] = datetime.now(ZoneInfo("Europe/Rome")).isoformat()
        LAST_REPLANNING_STATUS["last_success"] = True
        LAST_REPLANNING_STATUS["last_error"] = None
        LAST_REPLANNING_STATUS["last_result"] = result
        print(f"[Scheduler][Replanning] Ciclo completato: {result}")
    except Exception as e:
        LAST_REPLANNING_STATUS["last_finished_at"] = datetime.now(ZoneInfo("Europe/Rome")).isoformat()
        LAST_REPLANNING_STATUS["last_success"] = False
        LAST_REPLANNING_STATUS["last_error"] = str(e)
        print(f"[Scheduler][Replanning] Errore ciclo replanning: {e}")


def ensure_periodic_replanning_job():
    """Crea/aggiorna il job periodico replanning con intervallo runtime da configurazione."""
    interval_seconds = int(SERVICE_CONFIG.replanning_check_interval_seconds)
    scheduler.add_job(
        func=_run_periodic_replanning_job,
        trigger='interval',
        seconds=interval_seconds,
        id=REPLANNING_JOB_ID,
        name='Check periodico replanning',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )


def get_periodic_replanning_status():
    """Restituisce lo stato runtime del job periodico di replanning."""
    job = scheduler.get_job(REPLANNING_JOB_ID)
    return {
        "job_id": REPLANNING_JOB_ID,
        "configured_interval_seconds": int(SERVICE_CONFIG.replanning_check_interval_seconds),
        "scheduler_running": scheduler.running,
        "job_present": job is not None,
        "next_run_time": job.next_run_time.isoformat() if (job and job.next_run_time) else None,
        "last_execution": dict(LAST_REPLANNING_STATUS)
    }


def start_scheduler():
    """Avvia lo scheduler se non è già in esecuzione."""
    if not scheduler.running:
        scheduler.start()
    ensure_periodic_replanning_job()


def shutdown_scheduler():
    """Arresta lo scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)


def schedule_simulation_job(
    job_id: str,
    run_date: datetime,
    assegnazione_id: str,
    sim_speed_factor: float = 1.0
):
    """
    Schedula un job per l'esecuzione di una simulazione.
    
    Args:
        job_id: ID univoco del job
        run_date: Data/ora di esecuzione
        assegnazione_id: ID dell'assegnazione da simulare
        sim_speed_factor: Fattore di accelerazione simulazione
    """
    from app.services.simulatore_service import build_and_run_simulation
    from app.models.common import SimulationBuildInput, SimVesselInput
    
    def run_simulation():
        """Funzione wrapper per aggiornare stato e eseguire la simulazione."""
        try:
            # 1. Aggiorna lo stato dell'assegnazione a IN_CORSO
            patch_url = f"{OPERATIVO_SERVICE_URL.rstrip('/')}/internal/assegnazione/{assegnazione_id}/stato"
            patch_resp = requests.patch(
                patch_url,
                json={"stato_esecuzione": "IN_CORSO"},
                timeout=8,
            )
            if patch_resp.status_code >= 400:
                raise RuntimeError(f"update stato failed: HTTP {patch_resp.status_code}")
            print(f"[Scheduler] Stato assegnazione {assegnazione_id} aggiornato a IN_CORSO")
            
            # 2. Avvia la simulazione
            input_data = SimulationBuildInput(
                elementi=[
                    SimVesselInput(
                        assegnazione_id=assegnazione_id,
                        lat_start=None,
                        lon_start=None
                    )
                ],
                sim_speed_factor=sim_speed_factor
            )
            result = build_and_run_simulation(input_data)
            print(f"[Scheduler] Simulazione completata per assegnazione {assegnazione_id}: {result.get('status')}")
        except Exception as e:
            print(f"[Scheduler] Errore simulazione assegnazione {assegnazione_id}: {e}")
    
    scheduler.add_job(
        func=run_simulation,
        trigger='date',
        run_date=run_date,
        id=job_id,
        name=f"Simulazione assegnazione {assegnazione_id}",
        replace_existing=True
    )
    
    return job_id


def remove_simulation_job(job_id: str):
    """Rimuove un job schedulato."""
    try:
        scheduler.remove_job(job_id)
        return True
    except Exception:
        return False


def get_scheduled_jobs():
    """Restituisce la lista dei job schedulati."""
    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None
        }
        for job in jobs
    ]
