from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DeadheadCreateInput(BaseModel):
    """Schema per la creazione di un nuovo deadhead trip (viaggio a vuoto)."""
    orario_partenza_schedulato: datetime = Field(
        ...,
        description="Data/ora di partenza schedulata (ISO 8601)",
        example="2025-01-30T08:00:00"
    )
    porto_partenza_id: str = Field(
        ...,
        description="UUID del porto di partenza",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    porto_arrivo_id: str = Field(
        ...,
        description="UUID del porto di arrivo",
        example="550e8400-e29b-41d4-a716-446655440001"
    )
    idle: Optional[bool] = Field(
        False,
        description="True se il vascello è in attesa (idle) anziché in navigazione"
    )
    non_productive_time_min: Optional[float] = Field(
        None,
        description="Tempo non produttivo in minuti",
        ge=0,
        example=30.0
    )
    consumo: Optional[float] = Field(
        None,
        description="Consumo di carburante stimato (litri)",
        ge=0,
        example=150.0
    )
    vascello_id: str = Field(
        ...,
        description="UUID del vascello assegnato",
        example="550e8400-e29b-41d4-a716-446655440002"
    )
    piano_id: Optional[str] = Field(
        None,
        description="UUID del piano operativo di riferimento",
        example="550e8400-e29b-41d4-a716-446655440003"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "orario_partenza_schedulato": "2025-01-30T08:00:00",
                    "porto_partenza_id": "550e8400-e29b-41d4-a716-446655440000",
                    "porto_arrivo_id": "550e8400-e29b-41d4-a716-446655440001",
                    "idle": False,
                    "non_productive_time_min": 30.0,
                    "consumo": 150.0,
                    "vascello_id": "550e8400-e29b-41d4-a716-446655440002",
                    "piano_id": "550e8400-e29b-41d4-a716-446655440003"
                }
            ]
        }
    }


class DeadheadUpdateInput(BaseModel):
    """Schema per la modifica di un deadhead trip esistente."""
    id: str = Field(..., description="UUID del deadhead trip da modificare")
    orario_partenza_schedulato: Optional[datetime] = Field(None, description="Nuovo orario partenza")
    porto_partenza_id: Optional[str] = Field(None, description="Nuovo porto di partenza")
    porto_arrivo_id: Optional[str] = Field(None, description="Nuovo porto di arrivo")
    idle: Optional[bool] = Field(None, description="Nuovo stato idle")
    non_productive_time_min: Optional[float] = Field(None, description="Nuovo tempo non produttivo (min)", ge=0)
    consumo: Optional[float] = Field(None, description="Nuovo consumo (litri)", ge=0)
    vascello_id: Optional[str] = Field(None, description="Nuovo vascello")
    piano_id: Optional[str] = Field(None, description="Nuovo piano operativo")


class DeadheadDeleteInput(BaseModel):
    """Schema per l'eliminazione di un deadhead trip."""
    id: str = Field(
        ...,
        description="UUID del deadhead trip da eliminare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )


class DeadheadResponse(BaseModel):
    """Rappresentazione completa di un deadhead trip."""
    id: str = Field(..., description="UUID univoco del deadhead trip")
    orario_partenza_schedulato: datetime = Field(..., description="Data/ora partenza schedulata")
    porto_partenza_id: str = Field(..., description="UUID del porto di partenza")
    porto_arrivo_id: str = Field(..., description="UUID del porto di arrivo")
    idle: Optional[bool] = Field(None, description="True se il vascello è in idle")
    non_productive_time_min: Optional[float] = Field(None, description="Tempo non produttivo (min)")
    consumo: Optional[float] = Field(None, description="Consumo carburante (litri)")
    vascello_id: str = Field(..., description="UUID del vascello")
    piano_id: Optional[str] = Field(None, description="UUID del piano operativo")
