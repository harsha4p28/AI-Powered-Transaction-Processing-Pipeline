# AI-Powered Transaction Processing Pipeline

An asynchronous transaction processing pipeline built with **FastAPI**, **PostgreSQL**, **Celery**, **Redis**, and **Gemini 1.5 Flash (LLM)**. It processes financial transaction files, performs cleaning, detects statistical anomalies, classifies categories using batch LLM queries, and generates automated narrative summaries.

---

## 1. Architectural Overview & Data Flow

```mermaid
graph TD
    Client[Client / cURL] -->|1. POST CSV /jobs/upload| API[FastAPI Server]
    API -->|2. Create Job in DB| DB[(PostgreSQL)]
    API -->|3. Enqueue Job Task| Redis[(Redis Broker)]
    API -->|4. Return Job ID| Client
    
    Worker[Celery Worker] -->|5. Dequeue Job Task| Redis
    Worker -->|6. Process CSV Data| Clean[Pipeline: Cleaning & Anomalies]
    
    Clean -->|7. Batch Categorization| Gemini[Gemini 1.5 Flash API]
    Clean -->|8. Generate Narrative| Gemini
    
    Worker -->|9. Save Transactions & Summary| DB
    Worker -->|10. Mark Job Completed| DB
    
    Client -->|11. Poll Status / Results| API
    API -->|12. Fetch from DB| DB
```

### Request Lifecycle:
1. **Upload**: Client uploads `transactions.csv` to `/jobs/upload`. FastAPI parses metadata, inserts a `pending` Job record, and submits a Celery task.
2. **Processing**: Celery worker picks up the job and performs:
   - **Data Cleaning**: Date normalization (supporting multiple formats), currency symbol stripping, casing normalization, and deduplication.
   - **Anomaly Detection**: Calculates the account-level median to flag `amount > 3x median` as outliers, and flags domestic brands using `USD`.
   - **LLM Classification**: Batches uncategorized rows, prompting Gemini to classify them.
   - **LLM Summary**: Requests Gemini to summarize spends, calculate top merchants, and write a narrative overview.
3. **Polling**: Client queries `/jobs/{id}/status` and `/jobs/{id}/results` to view the structured results.

---

## 2. Database Schema

### `Job` Table
- `id` (UUID): Unique Job reference.
- `filename` (String): Raw CSV filename.
- `status` (String): `pending`, `processing`, `completed`, or `failed`.
- `row_count_raw` (Integer): Total rows imported.
- `row_count_clean` (Integer): Total deduplicated rows.
- `created_at` (DateTime): Timestamp of creation.
- `completed_at` (DateTime): Processing finish timestamp.
- `error_message` (Text): Details if job fails.

### `Transaction` Table
- `id` (Integer): Primary key.
- `job_id` (UUID): Associated Job.
- `txn_id` (String): Raw transaction ID.
- `date` (String): ISO normalized date `YYYY-MM-DD`.
- `merchant` (String): Merchant name.
- `amount` (Numeric): Normalized decimal value.
- `currency` (String): Normalized currency (`INR`, `USD`).
- `status` (String): Normalized transaction status.
- `category` (String): Standardized category.
- `account_id` (String): Customer account reference.
- `is_anomaly` (Boolean): Flagged if anomalous.
- `anomaly_reason` (String): Description of anomaly.
- `llm_category` (String): Category assigned by Gemini.
- `llm_failed` (Boolean): True if classification failed and fallback was used.

### `JobSummary` Table
- `id` (Integer): Primary key.
- `job_id` (UUID): Unique Job reference.
- `total_spend_inr` (Numeric): Aggregated success spend in INR.
- `total_spend_usd` (Numeric): Aggregated success spend in USD.
- `top_merchants` (JSON): Top 3 merchants by spend.
- `anomaly_count` (Integer): Count of anomalous transactions.
- `narrative` (Text): 2-3 sentence overview.
- `risk_level` (String): `low`, `medium`, or `high`.

---

## 3. Local Setup & Verification (Without Full Docker)

### Prerequisites
- Python 3.10+
- A running Redis instance.
- A running PostgreSQL database (or Supabase URL configured).

### 1. Configure `.env` File
Create a `.env` file in the root directory:
```ini
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=transactions_db
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/transactions_db

# Use localhost for local connection
REDIS_URL=redis://localhost:6379/0

GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-1.5-flash
```

### 2. Start Local Redis Broker
If you do not have Redis installed natively, start a standalone Redis container:
```powershell
docker run -d --name local-redis -p 6379:6379 redis:alpine
```

### 3. Run Automated Tests
```powershell
cd backend
python -m pytest
```

### 4. Start the Application Locally
In one terminal, start the FastAPI API server:
```powershell
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
In a second terminal, start the Celery worker:
```powershell
cd backend
python -m celery -A app.worker.celery_app worker --loglevel=info -P solo
```

---

## 4. Production/All-in-One Setup (With Docker Compose)

No local installation is required. This command starts the database, Redis, FastAPI, and the Celery worker.

```powershell
docker compose up --build
```
*Note: In the Docker environment, `REDIS_URL` is automatically configured to point to the `redis` container internal network (`redis://redis:6379/0`).*

To stop and clean up volumes:
```powershell
docker compose down -v
```

---

## 5. API Endpoints & Verification

Interactive Swagger UI documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs) when the API is running.

### 1. Upload a CSV
```bash
curl -X POST "http://localhost:8000/jobs/upload" \
  -F "file=@Backend_DevOps_Assignment/transactions.csv"
```
**Response**:
```json
{
  "job_id": "7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5",
  "status": "pending"
}
```

### 2. Check Job Status
```bash
curl "http://localhost:8000/jobs/7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5/status"
```
**Response (Processing)**:
```json
{
  "id": "7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5",
  "filename": "transactions.csv",
  "status": "processing",
  "row_count_raw": 96,
  "row_count_clean": 0,
  "created_at": "2026-06-29T12:00:00",
  "completed_at": null,
  "error_message": null,
  "summary": null
}
```

### 3. Fetch Job Results
```bash
curl "http://localhost:8000/jobs/7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5/results"
```
**Response**:
```json
{
  "job": {
    "id": "7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5",
    "filename": "transactions.csv",
    "status": "completed",
    "row_count_raw": 6,
    "row_count_clean": 5,
    "created_at": "2026-06-29T12:00:00",
    "completed_at": "2026-06-29T12:00:15",
    "error_message": null,
    "summary": {
      "total_spend_inr": 10982.55,
      "total_spend_usd": 2536.35,
      "top_merchants": [
        {"merchant": "Flipkart", "spend": 10882.55, "count": 1},
        {"merchant": "Zomato", "spend": 2536.35, "count": 1}
      ],
      "anomaly_count": 1,
      "narrative": "The spending analysis covers 5 clean transactions...",
      "risk_level": "medium"
    }
  },
  "transactions": [
    {
      "id": 1,
      "job_id": "7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5",
      "txn_id": "TXN1065",
      "date": "2024-09-04",
      "merchant": "Flipkart",
      "amount": 10882.55,
      "currency": "INR",
      "status": "SUCCESS",
      "category": "Shopping",
      "account_id": "ACC003",
      "is_anomaly": false,
      "anomaly_reason": null,
      "llm_category": null,
      "llm_raw_response": null,
      "llm_failed": false,
      "notes": "Refund expected"
    },
    {
      "id": 4,
      "job_id": "7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5",
      "txn_id": "TXN1021",
      "date": "2024-02-17",
      "merchant": "Zomato",
      "amount": 2536.35,
      "currency": "USD",
      "status": "SUCCESS",
      "category": "Food",
      "account_id": "ACC001",
      "is_anomaly": false,
      "anomaly_reason": null,
      "llm_category": "Food",
      "llm_raw_response": "[{\"index\": 0, \"category\": \"Food\"}]",
      "llm_failed": false,
      "notes": "Verified"
    }
  ],
  "category_spend_breakdown": {
    "Shopping": {
      "INR": 10882.55
    },
    "Food": {
      "USD": 2536.35
    }
  }
}
```

### 4. List All Jobs
```bash
curl "http://localhost:8000/jobs?status=completed"
```