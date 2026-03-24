import requests
from datetime import datetime
import json

def fetch_fills_2025():
    url = "https://api.hyperliquid.xyz/info"
    # Jan 1 2025 to Dec 31 2025
    start_time = int(datetime(2025, 1, 1).timestamp() * 1000)
    end_time = int(datetime(2025, 12, 31, 23, 59, 59).timestamp() * 1000)
    
    # Try different payload structures known in HyperLiquid
    payloads = [
        {"type": "userFills", "user": "0x880ac484a1743862989A441D6d867238c7AA311C", "startTime": start_time, "endTime": end_time},
        {"type": "userFillsByTime", "user": "0x880ac484a1743862989A441D6d867238c7AA311C", "startTime": start_time, "endTime": end_time}
    ]
    
    for data in payloads:
        print(f"Testing payload: {data['type']}")
        response = requests.post(url, json=data)
        try:
            fills = response.json()
            if isinstance(fills, list):
                print(f"Success! Fetched {len(fills)} fills.")
                if len(fills) > 0:
                    dt = datetime.fromtimestamp(fills[-1]['time'] / 1000)
                    print("Oldest fill date:", dt)
            else:
                print(f"Error response: {fills}")
        except Exception as e:
            print(f"Failed to parse JSON: {response.text}")

if __name__ == "__main__":
    fetch_fills_2025()
