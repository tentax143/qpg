# import requests

# # List of your worker nodes
# NODES = [f"172.16.71.{i}" for i in range(102, 141)]
# PORT = 11434

# def check_node(ip):
#     url = f"http://{ip}:{PORT}/api/tags"
#     try:
#         resp = requests.get(url, timeout=5)
#         resp.raise_for_status()
#         data = resp.json()
#         models = [m.get("name") for m in data.get("models", [])]
#         print(f"[OK] {ip} Ollama running. Models: {models}")
#     except Exception as e:
#         print(f"[FAIL] {ip} → {e}")

# if __name__ == "__main__":
#     for ip in NODES:
#         check_node(ip)
import boto3, json

client = boto3.client("bedrock-runtime", region_name="eu-north-1")

prompt = "Generate 3 CBSE Class XI Biology multiple-choice questions with answers."

body = {
    "messages": [
        {"role": "user", "content": [{"text": prompt}]}
    ],
    "inferenceConfig": {"temperature": 0.7, "maxTokens": 500}
}

response = client.invoke_model(
    modelId="arn:aws:bedrock:eu-north-1:659260838757:inference-profile/eu.amazon.nova-micro-v1:0",
    contentType="application/json",
    accept="application/json",
    body=json.dumps(body)
)

result = json.loads(response["body"].read())
text_output = result["output"]["message"]["content"][0]["text"]

print("\n📄 Generated Questions:\n")
print(text_output)

