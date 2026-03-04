from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime
from enum import Enum


class StatoEsecuzioneEnum(str, Enum):
    """Stati possibili del ciclo di vita di un'assegnazione."""
    PIANIFICATA = "PIANIFICATA"  # Assegnazione creata, in attesa di esecuzione
    IN_CORSO = "IN_CORSO"        # Assegnazione attualmente in esecuzione
    COMPLETATA = "COMPLETATA"    # Assegnazione terminata con successo
    CANCELLATA = "CANCELLATA"    # Assegnazione annullata


class AssegnazioneCreateInput(BaseModel):
    """Schema per la creazione di una nuova assegnazione operativa."""
    piano_id: Optional[str] = Field(
        None,
        description="UUID del piano operativo di riferimento (opzionale)",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    percorso_id: str = Field(
        ...,
        description="UUID del percorso da assegnare",
        example="550e8400-e29b-41d4-a716-446655440001"
    )
    stato_esecuzione: StatoEsecuzioneEnum = Field(
        ...,
        description="Stato iniziale dell'assegnazione",
        example="PIANIFICATA"
    )
    virtuale: Optional[bool] = Field(
        None,
        description="True se l'assegnazione è virtuale (simulazione/what-if)",
        example=False
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "piano_id": "550e8400-e29b-41d4-a716-446655440000",
                    "percorso_id": "550e8400-e29b-41d4-a716-446655440001",
                    "stato_esecuzione": "PIANIFICATA",
                    "virtuale": False
                }
            ]
        }
    }


class AssegnazioneResponse(BaseModel):
    """Rappresentazione completa di un'assegnazione operativa."""
    id: str = Field(..., description="UUID univoco dell'assegnazione")
    piano_id: Optional[str] = Field(None, description="UUID del piano operativo associato")
    vascello_id: str = Field(..., description="UUID del vascello assegnato")
    percorso_id: str = Field(..., description="UUID del percorso assegnato")
    id_corsa: Optional[str] = Field(None, description="UUID della corsa associata al percorso")
    stato_esecuzione: StatoEsecuzioneEnum = Field(..., description="Stato corrente dell'assegnazione")
    virtuale: Optional[bool] = Field(None, description="True se assegnazione virtuale")
    orario_completamento: Optional[datetime] = Field(None, description="Timestamp di completamento dell'assegnazione")


class AssegnazioneUpdateStatoInput(BaseModel):
    """Schema per l'aggiornamento dello stato di un'assegnazione."""
    stato_esecuzione: StatoEsecuzioneEnum = Field(
        ...,
        description="Nuovo stato dell'assegnazione",
        example="IN_CORSO"
    )


class AssegnazioneAPI(BaseModel):
    """Risposta API completa per dettaglio assegnazione con espansione relazioni."""
    id: str = Field(..., description="UUID univoco dell'assegnazione")
    piano_id: Optional[str] = Field(None, description="UUID del piano operativo associato")
    vascello_id: Optional[str] = Field(None, description="UUID del vascello assegnato")
    percorso_id: str = Field(..., description="UUID del percorso assegnato")
    id_corsa: Optional[str] = Field(None, description="UUID della corsa associata al percorso")
    stato_esecuzione: StatoEsecuzioneEnum = Field(..., description="Stato corrente dell'assegnazione")
    virtuale: Optional[bool] = Field(None, description="True se assegnazione virtuale")
    orario_completamento: Optional[datetime] = Field(None, description="Timestamp di completamento dell'assegnazione")
    piano: Optional[Dict[str, Any]] = Field(None, description="Dettaglio piano (espanso con ?include=piano)")
    percorso: Optional[Dict[str, Any]] = Field(None, description="Dettaglio percorso (espanso con ?include=percorso)")
    corsa: Optional[Dict[str, Any]] = Field(None, description="Dettaglio corsa (espanso con ?include=corsa)")
    vascello: Optional[Dict[str, Any]] = Field(None, description="Dettaglio vascello (espanso con ?include=vascello)")
