import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from decimal import Decimal
from app.database import Base
from app.models import Job, Transaction, JobSummary
from app.pipeline import process_job_data

# SQLite in-memory database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_pipeline_processing(db_session):
    # Sample dirty CSV data
    sample_csv = """txn_id,date,merchant,amount,currency,status,category,account_id,notes
TXN1065,04-09-2024,Flipkart,10882.55,INR,SUCCESS,Shopping,ACC003,Refund expected
TXN1054,2024/02/05,Swiggy,$100.00,INR,success,Food,ACC004,
TXN1054,2024/02/05,Swiggy,$100.00,INR,success,Food,ACC004,
TXN1021,17-02-2024,Zomato,2536.35,USD,SUCCESS,,ACC001,Verified
TXN1006,24-03-2024,IRCTC,10.00,USD,FAILED,Travel,ACC001,Refund expected
TXN1006,24-03-2024,IRCTC,1000.00,INR,FAILED,Travel,ACC001,Refund expected
"""
    # Create a job
    job = Job(
        filename="test_transactions.csv",
        status="pending",
        row_count_raw=0,
        row_count_clean=0
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    # Run pipeline
    process_job_data(db_session, job, sample_csv)

    # Refresh job
    db_session.refresh(job)
    
    # Assertions
    assert job.status == "completed"
    assert job.row_count_raw == 6  # 6 rows in CSV
    assert job.row_count_clean == 5  # 1 duplicate row removed
    
    # Check transactions
    transactions = db_session.query(Transaction).filter(Transaction.job_id == job.id).all()
    assert len(transactions) == 5
    
    # Verify cleaning
    # Check status normalization
    success_txs = [tx for tx in transactions if tx.status == "SUCCESS"]
    assert len(success_txs) == 3
    
    # Check amount normalization
    swiggy_tx = [tx for tx in transactions if tx.merchant == "Swiggy"][0]
    assert swiggy_tx.amount == Decimal("100.00")
    
    # Check date normalization (2024/02/05 -> 2024-02-05)
    assert swiggy_tx.date == "2024-02-05"
    
    # Check classification fallback for empty category
    zomato_tx = [tx for tx in transactions if tx.merchant == "Zomato"][0]
    assert zomato_tx.category == "Food"  # Zomato gets classified as Food by mock rules
    
    # Check anomalies
    # IRCTC USD transaction is a currency anomaly
    usd_irctc = [tx for tx in transactions if tx.merchant == "IRCTC" and tx.currency == "USD"][0]
    assert usd_irctc.is_anomaly is True
    assert "Currency anomaly" in usd_irctc.anomaly_reason
    
    # Median for ACC001: transactions has amounts 2536.35, 10.00, 1000.00
    # Sorted: 10.00, 1000.00, 2536.35. Median is 1000.00
    # 2536.35 is not > 3000.00, so no outlier anomaly
    # Let's check JobSummary
    summary = db_session.query(JobSummary).filter(JobSummary.job_id == job.id).first()
    assert summary is not None
    assert summary.anomaly_count == 1
    assert summary.risk_level == "medium"  # 1 anomaly -> medium risk
    assert summary.total_spend_inr > 0
