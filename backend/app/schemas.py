from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Any
from uuid import UUID
from datetime import datetime
from decimal import Decimal

class TransactionBase(BaseModel):
    txn_id: Optional[str] = None
    date: Optional[str] = None
    merchant: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    is_anomaly: bool = False
    anomaly_reason: Optional[str] = None
    llm_category: Optional[str] = None
    llm_failed: bool = False
    notes: Optional[str] = None

class TransactionResponse(TransactionBase):
    id: int
    job_id: UUID

    model_config = ConfigDict(from_attributes=True)

class JobSummaryBase(BaseModel):
    total_spend_inr: Decimal
    total_spend_usd: Decimal
    top_merchants: Optional[Any] = None
    anomaly_count: int
    narrative: Optional[str] = None
    risk_level: Optional[str] = None

class JobSummaryResponse(JobSummaryBase):
    id: int
    job_id: UUID

    model_config = ConfigDict(from_attributes=True)

class JobStatusResponse(BaseModel):
    id: UUID
    filename: str
    status: str
    row_count_raw: int
    row_count_clean: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    summary: Optional[JobSummaryBase] = None

    model_config = ConfigDict(from_attributes=True)

class JobResultsResponse(BaseModel):
    job: JobStatusResponse
    transactions: List[TransactionResponse]

    model_config = ConfigDict(from_attributes=True)

class JobListEntry(BaseModel):
    id: UUID
    filename: str
    status: str
    row_count_raw: int
    row_count_clean: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
