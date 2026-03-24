import requests
from datetime import datetime

def fetch_fills():
    url = "https://api.hyperliquid.xyz/info"
    data = {
        "type": "userFills",
        "user": "0x880ac484a1743862989A441D6d867238c7AA311C"
    }
    
    response = requests.post(url, json=data)
    fills = response.json()
    
    print(f"Fetched {len(fills)} total fills.")
    if fills:
        print("Sample fill keys:", list(fills[0].keys()))
        print("Sample fill:", fills[0])
        
        # Check for 2025 fills
        fills_2025 = []
        for f in fills:
            ts = f.get('time', 0) / 1000.0
            dt = datetime.fromtimestamp(ts)
            if dt.year == 2025:
                fills_2025.append(f)
        
        print(f"Total fills in 2025: {len(fills_2025)}")
        if fills_2025:
            print("First 2025 fill:", fills_2025[-1]) 
            print("Last 2025 fill:", fills_2025[0])

if __name__ == "__main__":
    fetch_fills()
