from pydantic import BaseModel, Field
from typing import Optional


class AllarmeResponse(BaseModel):
    id: str = Field(..., description="UUID allarme")
    utente_id: Optional[str] = Field(None, description="UUID utente associato")
    testo: str = Field(..., description="Messaggio allarme")
    data_creazione: Optional[str] = Field(None, description="Timestamp creazione (ISO 8601)")
