from pydantic import BaseModel, Field
from typing import Any, List, Optional, Union

from app.models.corsa import CorsaWithPrevisione
from app.models.tratta import TrattaDetail
from app.models.vascello import Vascello


class Passeggeri(BaseModel):
    """Informazioni passeggeri per un percorso."""
    capacita_vascello: Optional[int] = Field(None, description="Capacità massima del vascello assegnato")
    previsti: Optional[float] = Field(None, description="Passeggeri previsti (stima ML)")
    previsione_confidenza_min: Optional[float] = Field(None, description="Limite inferiore IC 95%")
    previsione_confidenza_max: Optional[float] = Field(None, description="Limite superiore IC 95%")
    data_previsione: Optional[Any] = Field(None, description="Timestamp della previsione")


class Percorso(BaseModel):
    """Rappresentazione di un percorso ottimizzato."""
    id: str = Field(..., description="UUID del percorso")
    corsa_id: str = Field(..., description="UUID della corsa associata")
    pref: Any = Field(..., description="Pressione di riferimento per l'ottimizzazione")
    vref: Any = Field(..., description="Velocità di riferimento in nodi")
    tempo_percorrenza: Any = Field(..., description="Tempo di percorrenza in minuti")
    consumo: Any = Field(..., description="Consumo carburante in litri")
    geom_rotta: str = Field(..., description="Geometria della rotta in formato GeoJSON")
    comfort: Any = Field(..., description="Indice di comfort (0-100)")
    distanza_nm: Any = Field(..., description="Distanza in miglia nautiche")
    vascello_id: Optional[str] = Field(None, description="UUID del vascello assegnato")


class PercorsoAPI(BaseModel):
    """Risposta API completa per un percorso con espansione dinamica relazioni."""
    percorso_id: str = Field(..., description="UUID del percorso")
    pref: Any = Field(..., description="Pressione di riferimento")
    vref: Any = Field(..., description="Velocità di riferimento (nodi)")
    tempo_percorrenza: Any = Field(..., description="Tempo percorrenza (minuti)")
    consumo: Any = Field(..., description="Consumo carburante (litri)")
    geom_rotta: str = Field(..., description="Geometria GeoJSON della rotta")
    comfort: Any = Field(..., description="Indice comfort navigazione (0-100)")
    distanza_nm: Any = Field(..., description="Distanza miglia nautiche")
    corsa: Optional[CorsaWithPrevisione] = Field(
        None, 
        description="Dati corsa (espanso con ?include=corsa)"
    )
    tratta: Optional[TrattaDetail] = Field(
        None, 
        description="Dati tratta (espanso con ?include=tratta)"
    )
    vascello: Optional[Vascello] = Field(
        None, 
        description="Dati vascello (espanso con ?include=vascello)"
    )


class PercorsoByCorsaItem(BaseModel):
    """Elemento percorso per lista corsa con espansione dinamica relazioni."""
    id: str = Field(..., description="UUID del percorso")
    corsa_id: str = Field(..., description="UUID della corsa associata")
    vascello_id: Optional[str] = Field(None, description="UUID del vascello assegnato")
    orario_partenza_schedulato: Optional[str] = Field(None, description="Orario partenza corsa (ISO 8601)")
    orario_arrivo_previsto: Optional[str] = Field(None, description="Orario arrivo stimato (ISO 8601)")
    passeggeri: Optional[Passeggeri] = Field(None, description="Informazioni passeggeri aggregate")
    consumo: Any = Field(..., description="Consumo carburante in litri")
    comfort: Any = Field(..., description="Indice di comfort (0-100)")
    distanza_nm: Any = Field(..., description="Distanza in miglia nautiche")
    pref: Any = Field(..., description="Pressione di riferimento per l'ottimizzazione")
    vref: Any = Field(..., description="Velocità di riferimento in nodi")
    tempo_percorrenza: Any = Field(..., description="Tempo di percorrenza in minuti")
    geom_rotta: str = Field(..., description="Geometria della rotta in formato GeoJSON")
    corsa: Optional[CorsaWithPrevisione] = Field(
        None,
        description="Dati corsa (espanso con ?include=corsa)"
    )
    tratta: Optional[TrattaDetail] = Field(
        None,
        description="Dati tratta (espanso con ?include=tratta)"
    )
    vascello: Optional[Vascello] = Field(
        None,
        description="Dati vascello (espanso con ?include=vascello)"
    )


class PercorsiByCorsa(BaseModel):
    """Lista percorsi associati a una corsa."""
    corsa_id: str = Field(..., description="UUID della corsa")
    percorsi: List[PercorsoByCorsaItem] = Field(..., description="Lista percorsi ottimizzati")
    

class PercorsoInserito(BaseModel):
    """Conferma inserimento percorso."""
    id: str = Field(..., description="UUID del percorso inserito")


class PercorsoAttivo(BaseModel):
    """Percorso attualmente in esecuzione per un vascello."""
    id: str = Field(..., description="UUID del percorso")
    corsa_id: str = Field(..., description="UUID della corsa")
    orario_partenza_schedulato: str = Field(..., description="Orario partenza (ISO 8601)")
    tratta_id: str = Field(..., description="UUID della tratta")
    tratta_nome: str = Field(..., description="Nome della tratta")
    tempo_percorrenza: float = Field(..., description="Tempo percorrenza previsto (minuti)")
    consumo: float = Field(..., description="Consumo previsto (litri)")


class DettaglioPercorsoAttivo(BaseModel):
    """Dettaglio di un singolo percorso attivo con relativa assegnazione."""
    assegnazione: dict = Field(..., description="Dati assegnazione {id, piano_id, virtuale}")
    percorso: PercorsoAttivo = Field(..., description="Dettagli percorso attivo")


class PercorsoAttivoResponse(BaseModel):
    """Risposta completa per i percorsi attivi di un vascello."""
    vascello: dict = Field(..., description="Dati vascello {id, mmsi, nome}")
    percorsi: List[DettaglioPercorsoAttivo] = Field(..., description="Lista percorsi attivi")


class PercorsoDeleteInput(BaseModel):
    """Schema per l'eliminazione di un percorso."""
    id: str = Field(
        ..., 
        description="UUID del percorso da eliminare",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
