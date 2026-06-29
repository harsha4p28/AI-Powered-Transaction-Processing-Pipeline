import os
import json
import time
import logging
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from .config import settings

logger = logging.getLogger(__name__)

# Initialize Google GenAI
if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your_gemini_api_key_here":
    genai.configure(api_key=settings.GEMINI_API_KEY)
    has_api_key = True
else:
    logger.warning("GEMINI_API_KEY not configured or using placeholder. Running in Mock/Rules-based mode.")
    has_api_key = False

def call_gemini_with_retry(prompt: str, response_json: bool = False, max_retries: int = 3, initial_delay: float = 1.0) -> str:
    """
    Calls Gemini API with exponential backoff retry logic.
    """
    if not has_api_key:
        raise ValueError("Gemini API key is not configured.")

    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    
    generation_config = {}
    if response_json:
        generation_config["response_mime_type"] = "application/json"

    delay = initial_delay
    for attempt in range(max_retries + 1):
        try:
            response = model.generate_content(
                prompt,
                generation_config=generation_config
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API call failed on attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries:
                raise e
            time.sleep(delay)
            delay *= 2  # Exponential backoff

def classify_transactions_batch(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Classify a batch of transactions using Gemini or fallback rules.
    Input format: [{"index": int, "merchant": str, "notes": str, "amount": float, "currency": str}]
    Returns: [{"index": int, "category": str}]
    """
    valid_categories = {"Food", "Shopping", "Travel", "Transport", "Utilities", "Cash Withdrawal", "Entertainment", "Other"}
    
    if not has_api_key:
        return mock_classify(transactions, valid_categories)
        
    prompt = f"""
    You are an expert financial transaction classifier.
    Classify the following batch of transactions into one of these categories: {", ".join(valid_categories)}.
    
    Input data (JSON list):
    {json.dumps(transactions)}

    Return a JSON array of objects with EXACTLY the following structure (no markdown boxes, just raw JSON array):
    [
      {{"index": 0, "category": "Food"}},
      {{"index": 1, "category": "Shopping"}}
    ]
    """
    try:
        response_text = call_gemini_with_retry(prompt, response_json=True)
        # Parse output
        results = json.loads(response_text)
        # Ensure format is a list and has valid categories
        if not isinstance(results, list):
            raise ValueError("LLM response is not a list")
            
        validated_results = []
        for item in results:
            cat = item.get("category", "Other")
            if cat not in valid_categories:
                cat = "Other"
            validated_results.append({
                "index": int(item.get("index")),
                "category": cat
            })
        return validated_results
    except Exception as e:
        logger.error(f"Failed to classify batch via LLM: {str(e)}. Falling back to rules-based classifier.")
        return mock_classify(transactions, valid_categories)

def generate_narrative_summary(summary_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a spending narrative and risk level using Gemini or fallback rules.
    """
    if not has_api_key:
        return mock_summary(summary_input)

    prompt = f"""
    Analyze the following aggregated transaction metrics and generate a spending summary.
    
    Metrics:
    {json.dumps(summary_input)}

    Return a JSON object containing:
    - total_spend_inr: {summary_input.get('total_spend_inr')}
    - total_spend_usd: {summary_input.get('total_spend_usd')}
    - top_merchants: list of top 3 merchants by spend (e.g. [{{"merchant": "...", "spend": 123.4, "count": 2}}])
    - anomaly_count: {summary_input.get('anomaly_count')}
    - narrative: a 2-3 sentence spending summary narrative highlighting any spending trends or anomalies.
    - risk_level: "low", "medium", or "high" (based on anomaly counts or suspicious activities).
    
    Return only valid raw JSON.
    """
    try:
        response_text = call_gemini_with_retry(prompt, response_json=True)
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Failed to generate narrative summary via LLM: {str(e)}. Falling back to rules-based summary.")
        return mock_summary(summary_input)

def mock_classify(transactions: List[Dict[str, Any]], valid_categories: set) -> List[Dict[str, Any]]:
    """
    Simple rules-based categorizer when LLM is unavailable or unconfigured.
    """
    results = []
    for tx in transactions:
        merchant = str(tx.get("merchant") or "").lower()
        notes = str(tx.get("notes") or "").lower()
        
        category = "Other"
        
        # Check merchant / notes rules
        if any(w in merchant or w in notes for w in ["swiggy", "zomato", "restaurant", "food", "cafeteria", "din"]):
            category = "Food"
        elif any(w in merchant or w in notes for w in ["amazon", "flipkart", "myntra", "shop", "grocer"]):
            category = "Shopping"
        elif any(w in merchant or w in notes for w in ["irctc", "makemytrip", "travel", "flight", "hotel", "trip"]):
            category = "Travel"
        elif any(w in merchant or w in notes for w in ["ola", "uber", "transport", "cab", "metro", "auto"]):
            category = "Transport"
        elif any(w in merchant or w in notes for w in ["jio", "recharge", "electricity", "power", "water", "bill"]):
            category = "Utilities"
        elif any(w in merchant or w in notes for w in ["atm", "withdrawal", "hdfc atm", "cash"]):
            category = "Cash Withdrawal"
        elif any(w in merchant or w in notes for w in ["netflix", "prime", "movie", "entertainment", "game"]):
            category = "Entertainment"
            
        results.append({
            "index": tx["index"],
            "category": category
        })
    return results

def mock_summary(summary_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fallback rules-based summary creator.
    """
    top_m = summary_input.get("top_merchants", [])[:3]
    anom_count = summary_input.get("anomaly_count", 0)
    
    risk_level = "low"
    if anom_count > 3:
        risk_level = "high"
    elif anom_count > 0:
        risk_level = "medium"
        
    narrative = f"The transaction analysis covers a total of {summary_input.get('total_count', 0)} transactions. "
    if top_m:
        narrative += f"The primary merchants by volume/spend were {', '.join([m['merchant'] for m in top_m])}. "
    if anom_count > 0:
        narrative += f"A total of {anom_count} anomalies were identified and flagged for review."
    else:
        narrative += "No suspicious anomalies or statistical outliers were detected."
        
    return {
        "total_spend_inr": summary_input.get("total_spend_inr", 0.0),
        "total_spend_usd": summary_input.get("total_spend_usd", 0.0),
        "top_merchants": top_m,
        "anomaly_count": anom_count,
        "narrative": narrative,
        "risk_level": risk_level
    }
