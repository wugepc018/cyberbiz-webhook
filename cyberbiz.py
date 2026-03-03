from flask import Flask,jsonify,request
import json
import os
import requests

app = Flask(__name__)
RSP_BASE_URL="https://web-production-ee85.up.railway.app"
RSP_SUBSCRIBE_API = f"{RSP_BASE_URL}/openapi/esim/plan/subscribe"
@app.route("/")
def health():
    return "OK", 200

@app.route("/webhook/cyberbiz/order", methods=["POST"])
def cyberbiz_order():
    data = request.get_json(silent=True)
    print(data)  
    return "ok", 200

@app.route("/order/esim", methods=["POST"])
def order_esim():
    data = request.get_json(silent=True)
    payload = {
        "planCode": data["product_code"],
        "email": data.get("email"),
        "qrcodeType": 0
    }
    headers = {
        "Content-Type": "application/json",
    }
    response=requests.post(RSP_SUBSCRIBE_API,json=payload,headers=headers,timeout=10)
    return jsonify({
    "rsp_status": response.status_code,
    "rsp_body": response.json()
        }), 200 
    
    {
    "planCode": "A-0001",
    "cid": "89852000010000000001",
    "qrcodeType": 0,
    "email": "abc@123.com"
    }
  

