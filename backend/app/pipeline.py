import csv
import io
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Tuple
from collections import defaultdict
from sqlalchemy.orm import Session
from .models import Job, Transaction, JobSummary
from .llm import classify_transactions_batch, generate_narrative_summary

logger = logging.getLogger(__name__)

def parse_date(date_str: str) -> str:
    """
    Normalizes date formats to ISO 8601 (YYYY-MM-DD).
    Supported formats: DD-MM-YYYY, YYYY/MM/DD, YYYY-MM-DD, DD/MM/YYYY, etc.
    """
    if not date_str:
        return ""
    date_str = date_str.strip()
    formats = [
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%Y.%m.%d"
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Return original if parsing fails
    return date_str

def parse_amount(amount_str: str) -> Decimal:
    """
    Strips currency symbols and whitespaces, converts to Decimal.
    """
    if not amount_str:
        return Decimal("0.00")
    # Remove $, commas, whitespace
    cleaned = amount_str.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")

def calculate_medians(rows: List[Dict[str, Any]]) -> Dict[str, Decimal]:
    """
    Calculates median transaction amount per account_id from the list of rows.
    """
    account_amounts = defaultdict(list)
    for r in rows:
        acc_id = r.get("account_id")
        amt = r.get("amount")
        if acc_id and amt is not None:
            account_amounts[acc_id].append(amt)
            
    medians = {}
    for acc_id, amts in account_amounts.items():
        if not amts:
            medians[acc_id] = Decimal("0.00")
            continue
        sorted_amts = sorted(amts)
        n = len(sorted_amts)
        if n % 2 == 1:
            medians[acc_id] = sorted_amts[n // 2]
        else:
            medians[acc_id] = (sorted_amts[n // 2 - 1] + sorted_amts[n // 2]) / Decimal("2")
    return medians

def process_job_data(db: Session, job: Job, csv_content: str):
    """
    Executes the complete transaction processing pipeline.
    """
    logger.info(f"Starting processing for job {job.id}")
    
    # Read CSV
    f = io.StringIO(csv_content.strip())
    reader = csv.DictReader(f)
    
    raw_rows = []
    for row in reader:
        # Strip keys and values
        clean_row = {k.strip(): (v.strip() if v else "") for k, v in row.items()}
        raw_rows.append(clean_row)
        
    job.row_count_raw = len(raw_rows)
    db.commit()
    
    # 1. Data Cleaning
    # Remove exact duplicates (based on the tuple of values)
    seen = set()
    cleaned_rows = []
    for r in raw_rows:
        # Make row hashable
        row_tuple = tuple(sorted(r.items()))
        if row_tuple not in seen:
            seen.add(row_tuple)
            
            # Normalize fields
            txn_id = r.get("txn_id") or None
            date_normalized = parse_date(r.get("date", ""))
            merchant = r.get("merchant", "")
            amount = parse_amount(r.get("amount", "0"))
            currency = r.get("currency", "").upper()
            status = r.get("status", "").upper()
            category = r.get("category", "")
            if not category:
                category = "Uncategorised"
            account_id = r.get("account_id", "")
            notes = r.get("notes", "") or None
            
            cleaned_rows.append({
                "txn_id": txn_id,
                "date": date_normalized,
                "merchant": merchant,
                "amount": amount,
                "currency": currency,
                "status": status,
                "category": category,
                "account_id": account_id,
                "notes": notes
            })
            
    job.row_count_clean = len(cleaned_rows)
    db.commit()
    
    # 2. Anomaly Detection
    medians = calculate_medians(cleaned_rows)
    domestic_brands = {"swiggy", "ola", "irctc"}
    
    for r in cleaned_rows:
        is_anomaly = False
        reasons = []
        
        # Check statistical outlier: amount > 3x median
        acc_id = r["account_id"]
        amt = r["amount"]
        median_val = medians.get(acc_id, Decimal("0.00"))
        
        if median_val > 0 and amt > 3 * median_val:
            is_anomaly = True
            reasons.append(f"Statistical outlier: amount exceeds 3x account median ({median_val})")
            
        # Check currency anomaly: USD with domestic merchant
        currency = r["currency"]
        merchant_lower = r["merchant"].lower()
        if currency == "USD" and merchant_lower in domestic_brands:
            is_anomaly = True
            reasons.append(f"Currency anomaly: USD transaction for domestic merchant ({r['merchant']})")
            
        r["is_anomaly"] = is_anomaly
        r["anomaly_reason"] = "; ".join(reasons) if is_anomaly else None
        
    # 3. LLM Classification for 'Uncategorised'
    uncategorized_items = []
    for idx, r in enumerate(cleaned_rows):
        if r["category"] == "Uncategorised":
            uncategorized_items.append({
                "index": idx,
                "merchant": r["merchant"],
                "amount": float(r["amount"]),
                "currency": r["currency"],
                "notes": r["notes"] or ""
            })
            
    # Process uncategorized in batches of 20
    batch_size = 20
    for i in range(0, len(uncategorized_items), batch_size):
        batch = uncategorized_items[i:i+batch_size]
        try:
            logger.info(f"Classifying batch of size {len(batch)}")
            classifications = classify_transactions_batch(batch)
            for res in classifications:
                idx = res["index"]
                category = res["category"]
                cleaned_rows[idx]["llm_category"] = category
                cleaned_rows[idx]["category"] = category
        except Exception as e:
            logger.error(f"Failed to process batch classification: {str(e)}")
            # Default fallback for this batch
            for item in batch:
                idx = item["index"]
                cleaned_rows[idx]["llm_category"] = "Other"
                cleaned_rows[idx]["category"] = "Other"
                cleaned_rows[idx]["llm_failed"] = True

    # 4. LLM Narrative Summary
    # Calculate spends (SUCCESS only for actual spend, or overall? Let's use SUCCESS transactions for spend statistics)
    total_spend_inr = Decimal("0.00")
    total_spend_usd = Decimal("0.00")
    merchant_spends = defaultdict(Decimal)
    merchant_counts = defaultdict(int)
    anomaly_count = 0
    
    for r in cleaned_rows:
        if r["is_anomaly"]:
            anomaly_count += 1
            
        # Standard spend metrics
        if r["status"] == "SUCCESS":
            if r["currency"] == "INR":
                total_spend_inr += r["amount"]
            elif r["currency"] == "USD":
                total_spend_usd += r["amount"]
                
            # Top merchants
            m = r["merchant"]
            if m:
                merchant_spends[m] += r["amount"]
                merchant_counts[m] += 1
                
    # Format top merchants
    sorted_merchants = sorted(merchant_spends.items(), key=lambda x: x[1], reverse=True)
    top_merchants_list = []
    for m, spend in sorted_merchants[:3]:
        top_merchants_list.append({
            "merchant": m,
            "spend": float(spend),
            "count": merchant_counts[m]
        })
        
    summary_input = {
        "total_spend_inr": float(total_spend_inr),
        "total_spend_usd": float(total_spend_usd),
        "top_merchants": top_merchants_list,
        "anomaly_count": anomaly_count,
        "total_count": len(cleaned_rows)
    }
    
    # Generate narrative summary
    summary_data = generate_narrative_summary(summary_input)
    
    # Save transactions to DB
    tx_objects = []
    for r in cleaned_rows:
        tx = Transaction(
            job_id=job.id,
            txn_id=r["txn_id"],
            date=r["date"],
            merchant=r["merchant"],
            amount=r["amount"],
            currency=r["currency"],
            status=r["status"],
            category=r["category"],
            account_id=r["account_id"],
            is_anomaly=r["is_anomaly"],
            anomaly_reason=r["anomaly_reason"],
            llm_category=r.get("llm_category"),
            llm_failed=r.get("llm_failed", False),
            notes=r["notes"]
        )
        tx_objects.append(tx)
        
    db.add_all(tx_objects)
    
    # Save summary to DB
    summary_obj = JobSummary(
        job_id=job.id,
        total_spend_inr=Decimal(str(summary_data.get("total_spend_inr", 0.0))),
        total_spend_usd=Decimal(str(summary_data.get("total_spend_usd", 0.0))),
        top_merchants=summary_data.get("top_merchants"),
        anomaly_count=summary_data.get("anomaly_count", 0),
        narrative=summary_data.get("narrative"),
        risk_level=summary_data.get("risk_level", "low")
    )
    db.add(summary_obj)
    
    job.status = "completed"
    job.completed_at = datetime.utcnow()
    db.commit()
    logger.info(f"Finished processing job {job.id} successfully.")
