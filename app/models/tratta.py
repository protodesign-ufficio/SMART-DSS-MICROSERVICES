from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID


class TrattaInputById(BaseModel):
    """Schema per la creazione di una tratta diretta tra due porti."""
    id: Optional[UUID] = Field(
        None,
        description="UUID opzionale per la tratta. Se non fornito, verrà generato automaticamente"
    )
    porto_partenza_id: UUID = Field(
        ...,
        description="UUID del porto di partenza",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    porto_arrivo_id: UUID = Field(
        ...,
        description="UUID del porto di arrivo",
        example="550e8400-e29b-41d4-a716-446655440001"
    )


class TrattaMultiInputById(BaseModel):
    """Schema per la creazione di una tratta multiporto con scali intermedi."""
    id: Optional[UUID] = Field(
        None,
        description="UUID opzionale per la tratta. Se non fornito, verrà generato automaticamente"
    )
    porti_ids: List[UUID] = Field(
        ...,
        description="Lista ordinata degli UUID dei porti (partenza, intermedi, arrivo). Minimo 2 porti richiesti",
        min_length=2,
        example=["uuid-porto-1", "uuid-porto-2", "uuid-porto-3"]
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "porti_ids": [
                        "550e8400-e29b-41d4-a716-446655440000",
                        "550e8400-e29b-41d4-a716-446655440001",
                        "550e8400-e29b-41d4-a716-446655440002"
                    ]
                }
            ]
        }
    }


class TrattaListItem(BaseModel):
    """Elemento sintetico per liste di tratte."""
    id: str = Field(..., description="UUID della tratta")
    nome: str = Field(..., description="Nome automatico della tratta (es. SAL-AMA)")
    porto_partenza_id: str = Field(..., description="UUID porto di partenza")
    porto_arrivo_id: str = Field(..., description="UUID porto di arrivo")
    porti_intermedi: Optional[List[str]] = Field(None, description="Lista UUID porti intermedi (se multiporto)")
    tratta_multiporto: bool = Field(..., description="True se la tratta ha scali intermedi")


class TrattaDetail(BaseModel):
    """Dettaglio completo di una tratta con geometria."""
    id: str = Field(..., description="UUID della tratta")
    nome: str = Field(..., description="Nome automatico della tratta")
    porto_partenza_id: str = Field(..., description="UUID porto di partenza")
    porto_arrivo_id: str = Field(..., description="UUID porto di arrivo")
    distanza_miglia: Optional[float] = Field(None, description="Distanza in miglia nautiche (nm)")
    porti_intermedi: Optional[List[str]] = Field(None, description="Lista UUID porti intermedi")
    tratta_multiporto: bool = Field(..., description="True se la tratta ha scali intermedi")
    geometry: str = Field(..., description="Geometria rotta in formato GeoJSON (LineString)")


class TrattaCreated(BaseModel):
    """Risposta alla creazione di una tratta diretta."""
    id: str = Field(..., description="UUID della tratta creata")
    nome: str = Field(..., description="Nome generato automaticamente")
    porto_partenza: str = Field(..., description="Nome del porto di partenza")
    porto_arrivo: str = Field(..., description="Nome del porto di arrivo")
    distanza_miglia: Optional[float] = Field(None, description="Distanza calcolata (nm)")
    geometry: str = Field(..., description="Geometria GeoJSON")


class TrattaMultiCreated(BaseModel):
    """Risposta alla creazione di una tratta multiporto."""
    id: str = Field(..., description="UUID della tratta creata")
    porti: List[str] = Field(..., description="Lista nomi porti in ordine")
    distanza_miglia: Optional[float] = Field(None, description="Distanza totale calcolata (nm)")
    porti_intermedi: Optional[List[str]] = Field(None, description="Nomi porti intermedi")
    tratta_multiporto: bool = Field(..., description="Sempre True per tratte multiporto")
    geometry: str = Field(..., description="Geometria GeoJSON completa")


class TrattaModificaInput(BaseModel):
    """Schema per la modifica di una tratta esistente."""
    id: str = Field(..., description="UUID della tratta da modificare")
    porto_partenza_id: str = Field(..., description="Nuovo UUID porto di partenza")
    porto_arrivo_id: str = Field(..., description="Nuovo UUID porto di arrivo")
