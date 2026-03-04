from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class VascelloInput(BaseModel):
    """Schema per la registrazione di un nuovo vascello nella flotta."""
    mmsi: Optional[str] = Field(
        None,
        description="Maritime Mobile Service Identity - Identificativo univoco IMO a 9 cifre",
        example="247123456",
        pattern=r"^\d{9}$"
    )
    nome: str = Field(
        ...,
        description="Nome della nave",
        example="Freccia del Golfo",
        min_length=2,
        max_length=100
    )
    capacita_passeggeri: Optional[int] = Field(
        None,
        description="Capacità massima passeggeri omologata",
        example=350,
        ge=1,
        le=5000
    )
    costo_orario_esercizio: Optional[float] = Field(
        None,
        description="Costo operativo orario in EUR (€/h)",
        example=450.00,
        ge=0
    )
    velocita_max_nodi: Optional[float] = Field(
        None,
        description="Velocità massima in nodi (kn)",
        example=28.5,
        ge=0,
        le=100
    )
    stato_salute_aggregato: Optional[float] = Field(
        None,
        description="Indice aggregato stato di salute (0-100). Valori bassi indicano necessità manutenzione",
        example=92.5,
        ge=0,
        le=100
    )
    profilo_consumo_json: Optional[dict] = Field(
        None,
        description="Profilo di consumo carburante parametrizzato per velocità. Formato: {velocita_kn: consumo_l_h}",
        example={"10": 45, "15": 78, "20": 125, "25": 195}
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "mmsi": "247123456",
                    "nome": "Freccia del Golfo",
                    "capacita_passeggeri": 350,
                    "costo_orario_esercizio": 450.00,
                    "velocita_max_nodi": 28.5,
                    "stato_salute_aggregato": 92.5,
                    "profilo_consumo_json": {"10": 45, "15": 78, "20": 125, "25": 195}
                }
            ]
        }
    }


class VascelloModificaInput(VascelloInput):
    """Schema per la modifica di un vascello esistente."""
    id: str = Field(
        ...,
        description="UUID del vascello da modificare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )


class VascelloDeleteInput(BaseModel):
    """Schema per l'eliminazione di un vascello."""
    id: str = Field(
        ...,
        description="UUID del vascello da eliminare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )


class Vascello(BaseModel):
    """Rappresentazione completa di un vascello della flotta."""
    id: str = Field(..., description="UUID univoco del vascello")
    mmsi: Optional[str] = Field(None, description="Maritime Mobile Service Identity (9 cifre)")
    nome: str = Field(..., description="Nome della nave")
    capacita_passeggeri: Optional[int] = Field(None, description="Capacità massima passeggeri")
    costo_orario_esercizio: Optional[float] = Field(None, description="Costo operativo orario (€/h)")
    velocita_max_nodi: Optional[float] = Field(None, description="Velocità massima (kn)")
    stato_salute_aggregato: Optional[float] = Field(None, description="Indice salute nave (0-100)")
    profilo_consumo_json: Optional[dict] = Field(None, description="Profilo consumo {velocità: consumo}")
    data_creazione: Optional[str] = Field(None, description="Timestamp creazione record (ISO 8601)")


class VascelloShort(BaseModel):
    """Rappresentazione sintetica di un vascello."""
    id: str = Field(..., description="UUID del vascello")
    mmsi: str = Field(..., description="Codice MMSI")
    nome: str = Field(..., description="Nome della nave")
