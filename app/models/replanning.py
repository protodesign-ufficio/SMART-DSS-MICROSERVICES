from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any


class ReplanningPercorsoInfo(BaseModel):
    """Dettaglio sintetico del percorso associato a un'assegnazione."""
    id: str = Field(..., description="UUID del percorso")
    tempo_percorrenza_min: Optional[float] = Field(
        None,
        description="Tempo di percorrenza stimato in minuti"
    )
    consumo: Optional[float] = Field(None, description="Consumo stimato del percorso")
    comfort: Optional[float] = Field(None, description="Indice comfort del percorso")
    vascello_id: Optional[str] = Field(None, description="UUID vascello associato al percorso")
    id_corsa: Optional[str] = Field(None, description="UUID corsa associata al percorso")


class ReplanningAssegnazioneItem(BaseModel):
    """Assegnazione raggruppata per vascello usata nel check di replanning."""
    id: str = Field(..., description="UUID dell'assegnazione")
    piano_id: Optional[str] = Field(None, description="UUID del piano operativo")
    vascello_id: str = Field(..., description="UUID del vascello assegnato")
    percorso_id: str = Field(..., description="UUID del percorso assegnato")
    id_corsa: Optional[str] = Field(None, description="UUID della corsa")
    stato_esecuzione: str = Field(..., description="Stato operativo assegnazione")
    virtuale: Optional[bool] = Field(None, description="Flag assegnazione virtuale")
    percorso: Optional[ReplanningPercorsoInfo] = Field(
        None,
        description="Dettaglio sintetico percorso"
    )
    corsa: Optional[Dict[str, Any]] = Field(
        None,
        description="Dettaglio corsa recuperato dal servizio corse"
    )


class CheckReplanningResponse(BaseModel):
    """Risposta dell'endpoint di verifica necessità replanning."""
    success: bool = Field(..., description="Esito complessivo della verifica")
    message: str = Field(..., description="Messaggio informativo dell'operazione")
    piano: Optional[Dict[str, Any]] = Field(
        None,
        description="Piano operativo con stato IN_CORSO per la data odierna"
    )
    assegnazioni_per_vascello: Dict[str, List[ReplanningAssegnazioneItem]] = Field(
        default_factory=dict,
        description="Mappa vascello_id -> lista assegnazioni arricchite"
    )
    mmsi_per_vascello: Dict[str, str] = Field(
        default_factory=dict,
        description="Mappa vascello_id -> MMSI"
    )
    risposta_replanning: Optional[Dict[str, Any]] = Field(
        None,
        description="Payload restituito dal servizio esterno di replanning"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "Piano IN_CORSO trovato con 3 assegnazioni su 2 vascelli",
                    "piano": {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "data_riferimento": "2026-02-18T00:00:00",
                        "stato": "IN_CORSO",
                        "kpi_profitto_stimato": 15200.4,
                        "kpi_robustezza": 84.1,
                        "versione": 2,
                        "assegnazioni": None
                    },
                    "assegnazioni_per_vascello": {
                        "vascello-1": [
                            {
                                "id": "asm-1",
                                "piano_id": "550e8400-e29b-41d4-a716-446655440000",
                                "vascello_id": "vascello-1",
                                "percorso_id": "percorso-1",
                                "id_corsa": "corsa-1",
                                "stato_esecuzione": "IN_CORSO",
                                "virtuale": False,
                                "percorso": {
                                    "id": "percorso-1",
                                    "tempo_percorrenza_min": 42.5,
                                    "consumo": 118.7,
                                    "comfort": 73.2,
                                    "vascello_id": "vascello-1",
                                    "id_corsa": "corsa-1"
                                },
                                "corsa": {
                                    "id": "corsa-1",
                                    "orario_partenza_schedulato": "2026-02-18T10:15:00"
                                }
                            }
                        ]
                    },
                    "mmsi_per_vascello": {
                        "vascello-1": "247123450"
                    },
                    "risposta_replanning": {
                        "success": True,
                        "needs_replanning": False,
                        "reason": "Nessuna criticità rilevata"
                    }
                }
            ]
        }
    }