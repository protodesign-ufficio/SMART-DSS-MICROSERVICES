from pydantic import BaseModel, Field
from typing import Optional, Any, List
from datetime import date
from app.models.tratta import TrattaDetail


class PrevisioneRequest(BaseModel):
    """Parametri per il calcolo della previsione domanda passeggeri."""
    biglietti_venduti_al_sample: float = Field(
        ...,
        description="Numero di biglietti venduti al momento della richiesta (dato di training ML)",
        example=120,
        ge=0
    )
    festivo: Optional[bool] = Field(
        None,
        description="Indica se la data della corsa è festiva. Se None, verrà determinato automaticamente",
        example=False
    )


class CorsaInput(BaseModel):
    """Schema per la creazione di una nuova corsa."""
    tratta_id: str = Field(
        ...,
        description="UUID della tratta di riferimento",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    data: str = Field(
        ...,
        description="Data della corsa in formato YYYY-MM-DD",
        example="2025-01-30"
    )
    orario: str = Field(
        ...,
        description="Orario di partenza schedulato (HH:MM o HHMM)",
        example="09:30"
    )
    orario_arrivo_max: Optional[str] = Field(
        None,
        description="Orario massimo di arrivo consentito (HH:MM o HHMM)",
        example="11:00"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tratta_id": "550e8400-e29b-41d4-a716-446655440000",
                    "data": "2025-01-30",
                    "orario": "09:30",
                    "orario_arrivo_max": "11:00"
                }
            ]
        }
    }


class CorsaInputModifica(BaseModel):
    """Campi modificabili di una corsa (tutti opzionali)."""
    tratta_id: Optional[str] = Field(None, description="Nuovo UUID tratta")
    data: Optional[str] = Field(None, description="Nuova data (YYYY-MM-DD)")
    orario: Optional[str] = Field(None, description="Nuovo orario partenza (HH:MM)")
    orario_arrivo_max: Optional[str] = Field(None, description="Nuovo orario arrivo max (HH:MM)")


class CorsaModificaInput(CorsaInputModifica):
    """Schema per la modifica di una corsa esistente."""
    id: str = Field(..., description="UUID della corsa da modificare")


class CorsaDeleteInput(BaseModel):
    """Schema per l'eliminazione di una corsa."""
    id: str = Field(..., description="UUID della corsa da eliminare")


class CorsaBase(BaseModel):
    """Rappresentazione base di una corsa."""
    id: str = Field(..., description="UUID della corsa")
    tratta_id: str = Field(..., description="UUID della tratta associata")
    orario_partenza_schedulato: str = Field(..., description="Orario partenza schedulato (ISO 8601)")
    previsione_domanda_id: Optional[str] = Field(None, description="UUID della previsione domanda associata")
    orario_arrivo_max: Optional[str] = Field(None, description="Orario arrivo massimo (ISO 8601)")


class CorsaCreated(BaseModel):
    """Risposta alla creazione di una corsa."""
    id: str = Field(..., description="UUID della corsa creata")
    nome: str = Field(..., description="Nome generato (TRATTA-YYYYMMDD-HHMM)")
    tratta_id: str = Field(..., description="UUID tratta associata")
    tratta_nome: str = Field(..., description="Nome della tratta")
    data: str = Field(..., description="Data della corsa")
    orario: str = Field(..., description="Orario di partenza")
    orario_partenza_schedulato: str = Field(..., description="Timestamp completo partenza (ISO 8601)")
    orario_arrivo_max: Optional[str] = Field(None, description="Timestamp arrivo max (ISO 8601)")


class CorsaGiornoItem(BaseModel):
    """Elemento corsa per visualizzazione giornaliera."""
    id: str = Field(..., description="UUID della corsa")
    nome: str = Field(..., description="Nome della corsa")
    tratta: str = Field(..., description="Nome della tratta")
    tratta_id: str = Field(..., description="UUID della tratta")
    orario: str = Field(..., description="Orario di partenza")
    orario_arrivo_max: Optional[str] = Field(None, description="Orario arrivo max")
    previsione: Optional["PrevisioneDomandaShort"] = Field(None, description="Dati previsione se disponibili")


class PrevisioneDomandaShort(BaseModel):
    """Previsione domanda passeggeri sintetica."""
    id: str = Field(..., description="UUID della previsione")
    passeggeri_stimati: float = Field(..., description="Numero passeggeri stimati dal modello ML")
    confidenza_min: Optional[float] = Field(None, description="Limite inferiore intervallo confidenza 95%")
    confidenza_max: Optional[float] = Field(None, description="Limite superiore intervallo confidenza 95%")
    created_at: Optional[Any] = Field(None, description="Timestamp creazione previsione")


class CorsaWithPrevisione(BaseModel):
    """Corsa con previsione domanda inclusa."""
    id: str = Field(..., description="UUID della corsa")
    nome: str = Field(..., description="Nome della corsa")
    tratta_id: str = Field(..., description="UUID tratta")
    tratta_nome: str = Field(..., description="Nome tratta")
    orario_partenza_schedulato: str = Field(..., description="Timestamp partenza (ISO 8601)")
    orario_arrivo_max: Optional[str] = Field(None, description="Timestamp arrivo max")
    previsione_domanda_id: Optional[str] = Field(None, description="UUID previsione associata")
    previsione: Optional[PrevisioneDomandaShort] = Field(None, description="Dati previsione se disponibili")


class CorsaAPI(BaseModel):
    """Risposta API completa per dettaglio corsa con espansione relazioni."""
    corsa_id: str = Field(..., description="UUID della corsa")
    nome: str = Field(..., description="Nome della corsa")
    orario_partenza_schedulato: str = Field(..., description="Timestamp partenza schedulato")
    orario_arrivo_max: Optional[str] = Field(None, description="Timestamp arrivo massimo")
    tratta: Optional[TrattaDetail] = Field(None, description="Tratta espansa (se richiesta con ?include=tratta)")
    previsione_domanda_id: Optional[str] = Field(None, description="UUID previsione")
    previsione: Optional[PrevisioneDomandaShort] = Field(None, description="Previsione passeggeri (sempre inclusa se presente)")
    percorsi: Optional[list] = Field(None, description="Percorsi espansi (se richiesti con ?include=percorsi)")


class PrevisioneResponse(BaseModel):
    """Risposta al calcolo previsione domanda."""
    corsa_id: str = Field(..., description="UUID della corsa")
    previsione_id: str = Field(..., description="UUID della previsione creata")
    passeggeri_stimati: float = Field(..., description="Stima passeggeri")
    dettagli: dict = Field(..., description="Dettagli tecnici della predizione ML")


class OrariResponse(BaseModel):
    """Lista orari disponibili per una tratta."""
    tratta_id: str = Field(..., description="UUID della tratta")
    tratta_nome: Optional[str] = Field(None, description="Nome tratta")
    orari: List[str] = Field(..., description="Lista orari di partenza disponibili")


class DashboardCorsaItem(BaseModel):
    """Elemento corsa per dashboard operativa."""
    corsa_id: str = Field(..., description="UUID corsa")
    corsa_nome: str = Field(..., description="Nome corsa")
    tratta_id: str = Field(..., description="UUID tratta")
    tratta_nome: str = Field(..., description="Nome tratta")
    orario: str = Field(..., description="Orario partenza")
    passeggeri: Optional[float] = Field(None, description="Passeggeri stimati")
    ci_min: Optional[float] = Field(None, description="Confidenza minima")
    ci_max: Optional[float] = Field(None, description="Confidenza massima")
