from pydantic import BaseModel, Field


class KafkaSettingsInput(BaseModel):
    """Parametri di configurazione per l'integrazione Kafka."""
    window_future: int = Field(
        30,
        description="Finestra temporale futura in minuti per la pubblicazione eventi",
        example=30,
        ge=1,
        le=1440
    )
    publish_interval: int = Field(
        30,
        description="Intervallo di pubblicazione messaggi in minuti",
        example=30,
        ge=1,
        le=1440
    )
    publish_interval_sec: int = Field(
        30,
        description="Intervallo di pubblicazione messaggi in secondi (granularità fine)",
        example=30,
        ge=1,
        le=3600
    )
    sim_speed_factor: float | None = Field(
        None,
        description="Fattore di accelerazione simulazione (opzionale, 1.0 = tempo reale, 2.0 = doppia velocità)",
        example=1.0,
        ge=0.1,
        le=100.0
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "window_future": 30,
                    "publish_interval": 30,
                    "publish_interval_sec": 30,
                    "sim_speed_factor": 1.0
                }
            ]
        }
    }


class KafkaSettingsResponse(BaseModel):
    """Stato corrente della configurazione Kafka."""
    window_future: int = Field(..., description="Finestra temporale futura (minuti)")
    publish_interval: int = Field(..., description="Intervallo pubblicazione (minuti)")
    publish_interval_sec: int = Field(..., description="Intervallo pubblicazione (secondi)")
    sim_speed_factor: float = Field(..., description="Fattore accelerazione simulazione")
    last_update: float = Field(..., description="Timestamp Unix dell'ultimo aggiornamento")
    timestamp: str = Field(..., description="Data/ora corrente (ISO 8601)")
