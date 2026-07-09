from finbert_sentiment import analyze_sentiment

# Add sentiment analysis function for tweets
def process_tweet_sentiment(text: str) -> tuple[float, str]:
    score, signal_type = analyze_sentiment(text)
    return score, signal_type