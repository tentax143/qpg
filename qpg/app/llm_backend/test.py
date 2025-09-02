import requests

# List of your worker nodes
NODES = [f"172.16.71.{i}" for i in range(102, 132)]
PORT = 11434

def check_node(ip):
    url = f"http://{ip}:{PORT}/api/tags"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [m.get("name") for m in data.get("models", [])]
        print(f"[OK] {ip} Ollama running. Models: {models}")
    except Exception as e:
        print(f"[FAIL] {ip} → {e}")

if __name__ == "__main__":
    for ip in NODES:
        check_node(ip)
