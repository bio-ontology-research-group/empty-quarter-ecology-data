import requests
import sys

API_BASE = "http://10.73.11.158:8080/api"

def test_root():
    print(f"Testing GET {API_BASE}/ ...", end=" ")
    try:
        r = requests.get(f"{API_BASE}/", timeout=5)
        if r.status_code == 200:
            print(f"PASS ({r.json()['message']})")
            return True
        else:
            print(f"FAIL (Status: {r.status_code})")
            return False
    except Exception as e:
        print(f"FAIL (Error: {e})")
        return False

def test_sites():
    print(f"Testing GET {API_BASE}/sites ...", end=" ")
    try:
        r = requests.get(f"{API_BASE}/sites", timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            print(f"PASS (Returned {len(data)} sites)")
            if len(data) > 0:
                print(f"  - Sample Site: {data[0]['label']}")
            return True
        else:
            print(f"FAIL (Status: {r.status_code})")
            return False
    except Exception as e:
        print(f"FAIL (Error: {e})")
        return False

def test_taxonomy():
    # We need a valid run label. Based on previous context, "59-MD1" or similar might exist.
    # But let's check what's in the SPARQL results if possible.
    # For now, let's try a known one or just check if it returns valid JSON even if empty.
    run_label = "ERR16062320" 
    print(f"Testing GET {API_BASE}/data/taxonomy?run_label={run_label} ...", end=" ")
    try:
        r = requests.get(f"{API_BASE}/data/taxonomy", params={"run_label": run_label}, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            print(f"PASS (Returned {len(data)} entries)")
            return True
        else:
            print(f"FAIL (Status: {r.status_code})")
            return False
    except Exception as e:
        print(f"FAIL (Error: {e})")
        return False

def test_xrf():
    print(f"Testing GET {API_BASE}/data/xrf ...", end=" ")
    try:
        r = requests.get(f"{API_BASE}/data/xrf", timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            print(f"PASS (Returned {len(data)} entries)")
            return True
        else:
            print(f"FAIL (Status: {r.status_code})")
            return False
    except Exception as e:
        print(f"FAIL (Error: {e})")
        return False

if __name__ == "__main__":
    print(f"--- Running API Tests against {API_BASE} ---")
    results = [
        test_root(),
        test_sites(),
        test_taxonomy(),
        test_xrf()
    ]
    
    if all(results):
        print("\nALL API TESTS PASSED.")
        sys.exit(0)
    else:
        print("\nSOME API TESTS FAILED.")
        sys.exit(1)
