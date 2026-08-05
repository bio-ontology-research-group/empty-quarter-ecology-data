import requests
import sys

API_BASE = "http://10.73.11.158:8080/api"

def test_xrf_process():
    print(f"Testing GET {API_BASE}/data/xrf?site_filter=Site 10 ...", end=" ")
    try:
        r = requests.get(f"{API_BASE}/data/xrf", params={"site_filter": "Site 10"}, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            print(f"PASS (Returned {len(data)} entries)")
            if len(data) > 0:
                first = data[0]
                print(f"  - Sample: {first.get('sample')}")
                print(f"  - Process: {first.get('process', 'MISSING')}")
                print(f"  - Source: {first.get('source', 'MISSING')}")
                
                if 'process' in first and 'source' in first:
                    return True
                else:
                    print("FAIL: 'process' or 'source' field missing in response.")
                    return False
            return True
        else:
            print(f"FAIL (Status: {r.status_code})")
            return False
    except Exception as e:
        print(f"FAIL (Error: {e})")
        return False

if __name__ == "__main__":
    if test_xrf_process():
        sys.exit(0)
    else:
        sys.exit(1)
