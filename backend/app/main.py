import logging
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from .database import get_db, engine, Base
from .models import Job, Transaction, JobSummary
from .schemas import JobStatusResponse, JobResultsResponse, JobListEntry
from .worker import process_transaction_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title="AI-Powered Transaction Processing Pipeline API",
    description="Asynchronously process and analyze financial transaction batches.",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized.")

@app.post("/jobs/upload", status_code=status.HTTP_201_CREATED)
async def upload_transactions(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Accept a CSV file upload. Validate it, create a Job record in the database
    with status=pending, enqueue the processing task, and return the job_id immediately.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only CSV files are supported."
        )

    try:
        content = await file.read()
        csv_content = content.decode("utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read/decode CSV file: {str(e)}"
        )

    # Save initial pending job to database
    db_job = Job(
        filename=file.filename,
        status="pending",
        row_count_raw=0,
        row_count_clean=0
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    # Dispatch Celery background task
    process_transaction_job.delay(str(db_job.id), csv_content)

    return {"job_id": db_job.id, "status": db_job.status}


@app.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: UUID, db: Session = Depends(get_db)):
    """
    Return the current status of the job: pending, processing, completed, or failed.
    If completed, also include a summary field with high-level stats.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    return job


@app.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: UUID, db: Session = Depends(get_db)):
    """
    Return the full structured output: cleaned transactions list, flagged anomalies,
    per-category spend breakdown, and the LLM-generated narrative summary.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is in state '{job.status}' and results are not available yet."
        )

    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    
    return {
        "job": job,
        "transactions": transactions
    }


@app.get("/jobs", response_model=List[JobListEntry])
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status (pending, processing, completed, failed)"),
    db: Session = Depends(get_db)
):
    """
    List all jobs with their status, filename, row count, and created_at timestamp.
    Supports filtering via ?status= query parameter.
    """
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status.lower())
    
    # Order by newest jobs first
    jobs = query.order_by(Job.created_at.desc()).all()
    return jobs
