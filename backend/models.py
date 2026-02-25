from pydantic import BaseModel

class DocumentSummary(BaseModel):
    summary: str
    key_points: list[str]
    language: str
    word_count: int