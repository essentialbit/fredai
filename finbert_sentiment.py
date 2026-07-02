"""FinBERT Domain-Specific Sentiment scoring module."""
import os
import psutil

# Flags for availability
HAS_FINBERT = False
_tokenizer = None
_model = None

# Hardware-check lite mode (Raspberry Pi Zero / 512MB RAM)
RAM_GB = psutil.virtual_memory().total / 1e9
LITE_MODE = RAM_GB < 1.0

if not LITE_MODE:
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        HAS_FINBERT = True
    except ImportError:
        # Fall back gracefully if packages are not installed yet
        HAS_FINBERT = False

def _init_model():
    """Lazily load FinBERT tokenizer and model to avoid import/cold-start latency."""
    global _tokenizer, _model
    if _tokenizer is not None and _model is not None:
        return
    
    if not HAS_FINBERT:
        raise ImportError("FinBERT dependencies (torch, transformers) are not available.")
    
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    # Load tokenizer and model
    _tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
    _model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")

def analyze_sentiment(text: str) -> tuple[float, str] | None:
    """Analyze sentiment of text using FinBERT model.
    
    Returns:
        tuple (score, signal_type) where score is -1.0 to 1.0, and signal_type is bullish/bearish/neutral.
        Returns None if FinBERT is unavailable or fails.
    """
    if not HAS_FINBERT or LITE_MODE:
        return None
        
    try:
        _init_model()
        import torch
        
        # Tokenize inputs
        inputs = _tokenizer(text, padding=True, truncation=True, max_length=512, return_tensors="pt")
        
        # Inference
        with torch.no_grad():
            outputs = _model(**inputs)
            
        # Logits mapping: FinBERT output is [positive, negative, neutral]
        logits = outputs.logits
        probs = torch.nn.functional.softmax(logits, dim=-1)[0]
        
        prob_pos = float(probs[0])
        prob_neg = float(probs[1])
        prob_neu = float(probs[2])
        
        # Compound score calculation: range from -1.0 to 1.0
        score = prob_pos - prob_neg
        
        # Signal type mapping
        if score >= 0.05:
            sig_type = "bullish"
        elif score <= -0.05:
            sig_type = "bearish"
        else:
            sig_type = "neutral"
            
        return score, sig_type
    except Exception as e:
        print(f"[FinBERT] Scoring error: {e}")
        return None
