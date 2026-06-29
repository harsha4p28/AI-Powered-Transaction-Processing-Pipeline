from celery import Celery
import logging
from .config import settings
from .database import SessionLocal
from .models import Job
from .pipeline import process_job_data

logger = logging.getLogger(__name__)

celery_app = Celery(
    "tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

# Celery settings
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(name="process_transaction_job")
def process_transaction_job(job_id: str, csv_content: str):
    logger.info(f"Celery task received for job {job_id}")
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found in database.")
            return False
            
        job.status = "processing"
        db.commit()
        
        process_job_data(db, job, csv_content)
        return True
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        db.rollback()
        # Reload job within fresh transaction context to write failure
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)
            db.commit()
        return False
    finally:
        db.close()
