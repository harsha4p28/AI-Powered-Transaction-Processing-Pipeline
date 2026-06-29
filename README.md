# AI-Powered Transaction Processing Pipeline

An asynchronous transaction processing pipeline built with FastAPI, PostgreSQL, Celery, Redis, and Gemini 1.5 Flash (LLM), fully containerized with Docker.

---

## 1. Prerequisites
- Python 3.10+
- PostgreSQL
- Redis
- Gemini API Key (Optional; fallback rules-based processing will run if not provided)

---

## 2. Local Setup & Execution

### Setup Environment
1. Copy the template env file:
   ```bash
   cp .env.example .env
   ```
2. Configure the values in `.env` (database credentials, Redis URL, and `GEMINI_API_KEY`).

### Run Tests
To run the automated test suite locally:
```bash
cd backend
python -m pytest
```

### Start Services Locally
1. **Start PostgreSQL and Redis** on your system.
2. **Start the FastAPI App**:
   ```bash
   cd backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
3. **Start the Celery Worker**:
   ```bash
   cd backend
   celery -A app.worker.celery_app worker --loglevel=info
   ```

---

## 3. Running with Docker Compose (Recommended)

To spin up the entire system (FastAPI app, Celery worker, Redis, PostgreSQL) with a single command:
```bash
docker compose up --build
```
This automatically sets up all database tables and links the services.

---

## 4. API Endpoints & Curl Examples

### Upload a CSV Job
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

### Check Job Status
```bash
curl "http://localhost:8000/jobs/7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5/status"
```

### Retrieve Job Results
```bash
curl "http://localhost:8000/jobs/7ac148c3-4dbe-47be-a5e2-6cf2153b6cb5/results"
```

### List All Jobs
```bash
curl "http://localhost:8000/jobs?status=completed"
```