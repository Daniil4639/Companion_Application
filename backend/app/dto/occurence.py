from datetime import datetime

from pydantic import BaseModel


class MoveOccurrenceRequest(BaseModel):
    start_at: datetime
    finish_at: datetime


class CancelOccurrenceResponse(BaseModel):
    status: str