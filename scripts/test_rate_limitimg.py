import requests
import time

API_BASE = "http://127.0.0.1:8000/api"

def test_rate_limiting():
    print("Testing Rate Limiting (10 requests per minute limit)...")
    for i in range(12):
        response = requests.post(
            f"{API_BASE}/query",
            json={"question": "hello"},
            headers={"X-Tenant-ID": "test_tenant"}
        )
        if response.status_code == 429:
            print(f"Request {i+1}: Blocked! 429 Too Many Requests (Rate limit working)")
            break
        else:
            print(f"Request {i+1}: {response.status_code}")
    print("-" * 50)

def test_tenant_isolation():
    print("Testing Tenant Isolation...")
    # Assume Tenant_A asks a question
    response_a = requests.post(
        f"{API_BASE}/query",
        json={"question": "What is the PUE efficiency?"},
        headers={"X-Tenant-ID": "Tenant_A"}
    )
    print("Tenant A Query Status:", response_a.status_code)
    
    response_b = requests.post(
        f"{API_BASE}/query",
        json={"question": "What is the PUE efficiency?"},
        headers={"X-Tenant-ID": "Tenant_B"}
    )
    print("Tenant B Query Status:", response_b.status_code)

if __name__ == "__main__":
    try:
        test_rate_limiting()
        test_tenant_isolation()
    except Exception as e:
        print(f"Failed to connect to API. Make sure uvicorn api.main:app is running. Error: {e}")
