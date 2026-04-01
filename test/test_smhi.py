import asyncio
import aiohttp
import json
from datetime import datetime, timezone

async def test_smhi_debug():
    lat_str = "55.70584"
    lon_str = "13.19321"
    url = f"https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/{lon_str}/lat/{lat_str}/data.json"
    
    print(f"Fetching from: {url}")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            print(f"HTTP Status: {response.status}")
            try:
                data = await response.json()
            except Exception as e:
                text = await response.text()
                print(f"Failed to parse JSON. Error: {e}")
                print(f"Raw text:\n{text[:1000]}")
                return

    print("\n--- RAW JSON TOP-LEVEL KEYS ---")
    print(list(data.keys()))
    
    print("\n--- RAW JSON SNIPPET (First 1000 chars) ---")
    print(json.dumps(data, indent=2)[:1000])

    times = []
    if 'timeSeries' in data:
        for entry in data['timeSeries']:
            dt_str = entry.get('validTime')
            if dt_str:
                times.append(datetime.fromisoformat(dt_str.replace('Z', '+00:00')))
    else:
        print("\n[!] 'timeSeries' key is missing. SMHI must be using a different structure for SNOW1gv1.")

    if times:
        print(f"\n--- SMHI DATA SUMMARY ---")
        print(f"Total data points: {len(times)}")
        print(f"First timestamp (Oldest): {times[0]}")
        print(f"Last timestamp  (Newest): {times[-1]}")

if __name__ == "__main__":
    asyncio.run(test_smhi_debug())