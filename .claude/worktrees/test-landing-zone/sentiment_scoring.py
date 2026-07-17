from transformers import pipeline

finbert = pipeline('text-classification', model='ProsusAI/finbert', device=-1)

def analyze_sentiment(text):
    result = finbert(text)
    return result[0]['score']