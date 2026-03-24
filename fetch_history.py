import requests
from datetime import datetime
import json
import time

def fetch_2025_forward():
    url = "https://api.hyperliquid.xyz/info"
    user = "0x880ac484a1743862989A441D6d867238c7AA311C"
    
    # Target 2025
    current_start = int(datetime(2026, 1, 1).timestamp() * 1000)
    target_end = int(datetime(2026, 12, 31, 23, 59, 59).timestamp() * 1000)
    
    all_fills = []
    
    print("Paginating FORWARD to fetch fills for 2026...")
    
    while True:
        resp = requests.post(url, json={
            "type": "userFillsByTime",
            "user": user,
            "startTime": current_start,
            "endTime": target_end
        })
        
        try:
            fills = resp.json()
        except:
            print("Failed to parse response:", resp.text)
            break
            
        if not isinstance(fills, list) or len(fills) == 0:
            print("No more fills found.")
            break
            
        # fills in userFillsByTime are sorted oldest first
        t_first = fills[0]['time']
        t_last = fills[-1]['time']
        
        newest_time_in_batch = t_last
        
        all_fills.extend(fills)
        print(f"Fetched {len(fills)} fills. Batch spans: {datetime.fromtimestamp(t_first / 1000)} to {datetime.fromtimestamp(t_last / 1000)}")
        
        if len(fills) < 2000:
            print("Reached the end of the requested timeframe (less than 2000 returned).")
            break
            
        # To avoid infinite loop where all 2000 fills have the exact same ms timestamp
        if current_start == newest_time_in_batch:
            current_start += 1
        else:
            current_start = newest_time_in_batch + 1
            
        time.sleep(0.2) # rate limit protection

    print(f"Total 2025 fills fetched: {len(all_fills)}")
    
    with open("fills_2025.json", "w") as f:
        json.dump(all_fills, f)

if __name__ == "__main__":
    fetch_2025_forward()
