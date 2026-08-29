import requests
import sys

API_BASE = "http://10.73.11.158:8080/api"

def test_samples():
    site_label = "Site 10"
    print(f"Testing GET {API_BASE}/samples?site_label={site_label} ...", end=" ")
    try:
        r = requests.get(f"{API_BASE}/samples", params={"site_label": site_label}, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            print(f"PASS (Returned {len(data)} entries)")
            if len(data) > 0:
                print(f"  - Sample: {data[0]['soilSample']}")
                print(f"  - Run: {data[0]['run']}")
            return True
        else:
            print(f"FAIL (Status: {r.status_code})")
            print(r.text)
            return False
    except Exception as e:
        print(f"FAIL (Error: {e})")
        return False

if __name__ == "__main__":
    test_samples()
