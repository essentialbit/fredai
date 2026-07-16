import pandas as pd
import numpy as np

def calculate_rolling_correlation(df, window_days=[30, 90, 180]):
    """Compute rolling cross-asset correlation matrices for specified windows."
    
    # Ensure df is sorted by date
    df = df.sort_index()
    
    correlations = {}
    for window in window_days:
        # Compute rolling correlation
        rolling_corr = df.rolling(window=window).corr()
        correlations[window] = rolling_corr
    
    # Store results in memory store (global variable)
    global memory_store
    memory_store = correlations
    
    # Check for threshold and trigger alerts
    for window in window_days:
        if correlations[window].abs().max() > 0.8:
            # Trigger alert via SocketIO
            print(f"Alert: Correlation threshold exceeded for {window} days")
    
    return correlations