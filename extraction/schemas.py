from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class Person(BaseModel):
    prenom: Optional[str] = None
    nom: Optional[str] = None
    telephone: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    date_naissance: Optional[str] = None
    numero_piece: Optional[str] = None
    adresse: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class OCRResult(BaseModel):
    raw_text: str
    confidence_scores: Optional[List[float]] = None


class ProcessDocumentResponse(BaseModel):
    raw_text: str
    persons: List[Person]
    count: int
