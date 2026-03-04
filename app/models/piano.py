from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.assegnazione import AssegnazioneResponse


class PianoCreateInput(BaseModel):
    """Schema per la creazione di un nuovo piano operativo."""
    data_riferimento: datetime = Field(
        ...,
        description="Data e ora di riferimento del piano operativo (ISO 8601)",
        example="2025-01-30T00:00:00"
    )
    stato: str = Field(
        ...,
        description="Stato iniziale del piano. Valori: CREATO, IN_OTTIMIZZAZIONE, PRONTO, ATTIVO, ARCHIVIATO, ERRORE",
        example="CREATO"
    )
    kpi_profitto_stimato: Optional[float] = Field(
        None,
        description="KPI profitto stimato in EUR",
        example=15000.50
    )
    kpi_robustezza: Optional[float] = Field(
        None,
        description="KPI robustezza della pianificazione (0-100)",
        example=87.5,
        ge=0,
        le=100
    )
    versione: Optional[int] = Field(
        None,
        description="Numero versione per tracciamento modifiche",
        example=1,
        ge=1
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "data_riferimento": "2025-01-30T00:00:00",
                    "stato": "CREATO",
                    "kpi_profitto_stimato": 15000.50,
                    "kpi_robustezza": 87.5,
                    "versione": 1
                }
            ]
        }
    }


class PianoResponse(BaseModel):
    """Rappresentazione completa di un piano operativo."""
    id: str = Field(..., description="UUID univoco del piano")
    data_riferimento: datetime = Field(..., description="Data/ora di riferimento")
    stato: str = Field(..., description="Stato corrente del piano")
    kpi_profitto_stimato: Optional[float] = Field(None, description="KPI profitto stimato (EUR)")
    kpi_robustezza: Optional[float] = Field(None, description="KPI robustezza (0-100)")
    versione: Optional[int] = Field(None, description="Numero versione")
    assegnazioni: Optional[List[AssegnazioneResponse]] = Field(
        None, 
        description="Lista assegnazioni associate al piano (se richieste)"
    )


class PianoUpdateInput(BaseModel):
    """Schema per la modifica di un piano operativo esistente."""
    id: str = Field(..., description="UUID del piano da modificare")
    data_riferimento: Optional[datetime] = Field(None, description="Nuova data riferimento")
    stato: Optional[str] = Field(None, description="Nuovo stato del piano")
    kpi_profitto_stimato: Optional[float] = Field(None, description="Nuovo KPI profitto")
    kpi_robustezza: Optional[float] = Field(None, description="Nuovo KPI robustezza")
    versione: Optional[int] = Field(None, description="Nuova versione")


class PianoDeleteInput(BaseModel):
    """Schema per l'eliminazione di un piano operativo."""
    id: str = Field(
        ...,
        description="UUID del piano da eliminare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )


class PianoValidaInput(BaseModel):
    """Schema per la validazione di un piano operativo."""
    piano_id: str = Field(
        ...,
        description="UUID del piano da validare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )


class SimulazioneSchedulataItem(BaseModel):
    """Dettaglio di una simulazione schedulata."""
    assegnazione_id: str = Field(..., description="UUID dell'assegnazione")
    orario_simulazione: str = Field(..., description="Orario schedulato per la simulazione (ISO 8601)")
    job_id: str = Field(..., description="ID del job schedulato")


class PianoValidaResponse(BaseModel):
    """Risposta alla validazione di un piano operativo."""
    piano_id: str = Field(..., description="UUID del piano validato")
    stato: str = Field(..., description="Nuovo stato del piano")
    validato: bool = Field(..., description="True se il piano è stato validato con successo")
    messaggio: str = Field(..., description="Messaggio informativo o di errore")
    corse_giorno: int = Field(0, description="Numero di corse nel giorno del piano")
    assegnazioni_pianificate: int = Field(0, description="Numero di assegnazioni PIANIFICATE trovate")
    simulazioni_schedulate: int = Field(0, description="Numero di simulazioni schedulate")
    dettaglio_simulazioni: Optional[List[SimulazioneSchedulataItem]] = Field(
        None, 
        description="Dettaglio simulazioni schedulate"
    )