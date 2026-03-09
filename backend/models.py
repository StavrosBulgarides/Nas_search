from __future__ import annotations

from pydantic import BaseModel
from typing import List, Optional


class FileResult(BaseModel):
    id: int
    filename: str
    folder_path: str
    full_path: str
    extension: Optional[str]
    size: int
    modified_date: float
    score: float = 0.0


class SearchResponse(BaseModel):
    results: List[FileResult]
    total: int
    query: str
    fuzzy: bool = False


class IndexStatus(BaseModel):
    total_files: int
    last_index_time: Optional[str]
    last_index_duration: Optional[float]
    indexing_in_progress: bool


class TrackClick(BaseModel):
    folder_path: str
