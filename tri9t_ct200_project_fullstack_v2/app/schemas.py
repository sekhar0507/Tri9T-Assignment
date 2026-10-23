from pydantic import BaseModel, Field
from typing import Any

class IngestResponse(BaseModel):
    document_key: str
    version_id: int
    version_number: int
    node_count: int
    source_sha256: str
    changes: dict[str, int]

class SelectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    node_ids: list[int] = Field(min_length=1)

class TestCase(BaseModel):
    title: str = Field(min_length=3)
    requirement: str
    preconditions: list[str] = []
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=3)
    severity: str = "medium"
    traceability: list[str] = []

class GenerationResponse(BaseModel):
    generation_id: int
    selection_id: int
    provider: str
    status: str
    test_cases: list[TestCase]
    warnings: list[str]
    staleness: dict[str, Any]
