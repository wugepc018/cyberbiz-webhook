from flask import Flask,jsonify,request
import json
import os
import requests
import hmac
import hashlib
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "Webhook server running"

@app.route("/webhook/cyberbiz/order", methods=["POST"])
def cyberbiz_order():

    data = request.json
    print("Webhook received:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return jsonify({
        "status": "ok"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


