import requests
import time
import json

WEBHOOK_URL = "https://unusualwhales.com/webhook"

def process_event(event):
    print(f"Received unusual whales event: {event}")

def start_listener():
    while True:
        try:
            response = requests.get(WEBHOOK_URL)
            if response.status_code == 200:
                event_data = response.json()
                process_event(event_data)
            time.sleep(5)
        except Exception as e:
            print(f"Error in listener: {e}")
            time.sleep(10)

if __name__ == "__main__":
    start_listener()