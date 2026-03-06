from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ComponenteInput(BaseModel):
    """Schema per la creazione di un componente di vascello."""
    vascello_id: Optional[str] = Field(
        None,
        description="UUID del vascello associato",
        example="550e8400-e29b-41d4-a716-446655440000",
    )
    nome_componente: str = Field(
        ...,
        description="Nome identificativo del componente",
        example="Motore principale SX",
        min_length=1,
        max_length=200,
    )
    sottosistema: Optional[str] = Field(
        None,
        description="Sottosistema di appartenenza",
        example="Propulsione",
        max_length=200,
    )
    ore_utilizzo_totali: Optional[float] = Field(
        None,
        description="Ore cumulative di funzionamento",
        example=1234.5,
        ge=0,
    )
    soglia_manutenzione: Optional[float] = Field(
        None,
        description="Soglia ore per manutenzione programmata",
        example=1500.0,
        ge=0,
    )
    modello_guasto_json: Optional[Dict[str, Any]] = Field(
        None,
        description="Configurazione modello guasto in formato JSON",
        example={"type": "weibull", "shape": 1.8, "scale": 2200},
    )


class ComponenteModificaInput(ComponenteInput):
    """Schema per la modifica di un componente esistente."""
    id: str = Field(
        ...,
        description="UUID del componente da modificare",
        example="550e8400-e29b-41d4-a716-446655440111",
    )


class ComponenteDeleteInput(BaseModel):
    """Schema per l'eliminazione di un componente."""
    id: str = Field(
        ...,
        description="UUID del componente da eliminare",
        example="550e8400-e29b-41d4-a716-446655440111",
    )


class Componente(BaseModel):
    """Rappresentazione completa di un componente."""
    id: str = Field(..., description="UUID del componente")
    vascello_id: Optional[str] = Field(None, description="UUID del vascello associato")
    nome_componente: str = Field(..., description="Nome del componente")
    sottosistema: Optional[str] = Field(None, description="Sottosistema")
    ore_utilizzo_totali: Optional[float] = Field(None, description="Ore cumulative di utilizzo")
    soglia_manutenzione: Optional[float] = Field(None, description="Soglia ore manutenzione")
    modello_guasto_json: Optional[Dict[str, Any]] = Field(None, description="Modello guasto JSON")
