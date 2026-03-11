import requests

url = "http://127.0.0.1:8080/webhook/cyberbiz/order"

data = {
    "order_number": "ORDER123",
    "customer": {
        "email": "test@example.com"
    },
    "line_items": [
        {"product_id": "PROD001", "qc": "AUTO001"},
        {"product_id": "PROD002", "qc": "MANUAL"}
    ]
}

r = requests.post(url, json=data)
print(r.json())