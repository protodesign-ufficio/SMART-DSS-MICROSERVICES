from pydantic import BaseModel, Field
from typing import Optional, List


class PortoInput(BaseModel):
    """Schema per la creazione di un nuovo porto."""
    nome: str = Field(
        ...,
        description="Nome identificativo del porto (es. città, località)",
        example="Salerno",
        min_length=2,
        max_length=100
    )
    lat: float = Field(
        ...,
        description="Latitudine GPS in gradi decimali (WGS84)",
        example=40.6824,
        ge=-90.0,
        le=90.0
    )
    lon: float = Field(
        ...,
        description="Longitudine GPS in gradi decimali (WGS84)",
        example=14.7681,
        ge=-180.0,
        le=180.0
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "nome": "Salerno",
                    "lat": 40.6824,
                    "lon": 14.7681
                }
            ]
        }
    }


class PortoModificaInput(PortoInput):
    """Schema per la modifica di un porto esistente."""
    id: str = Field(
        ...,
        description="UUID del porto da modificare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )


class PortoDeleteInput(BaseModel):
    """Schema per l'eliminazione di un porto."""
    id: str = Field(
        ...,
        description="UUID del porto da eliminare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )


class Porto(BaseModel):
    """Rappresentazione completa di un porto."""
    id: str = Field(..., description="UUID univoco del porto")
    nome: str = Field(..., description="Nome identificativo del porto")
    lat: float = Field(..., description="Latitudine GPS (WGS84)")
    lon: float = Field(..., description="Longitudine GPS (WGS84)")
