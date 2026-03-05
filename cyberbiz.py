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
    print("Webhook received:", data)

    return jsonify({
        "status": "ok"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


'''
APP_SECRET=os.getenv("CYBERBIZ_APP_SECRET")

if not APP_SECRET:
    print("WARNING: CYBERBIZ_APP_SECRET not set")
def verify_signature(request):
    signature = request.headers.get("X-Cyberbiz-Signature")
    if not signature:
        return False
    raw_body = request.data

    computed = hmac.new(
        APP_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, signature)

app = Flask(__name__)
RSP_BASE_URL="https://cyberbiz-webhook-production.up.railway.app"
RSP_SUBSCRIBE_API = f"{RSP_BASE_URL}/openapi/esim/plan/subscribe"

@app.errorhandler(Exception)
def handle_exception(e):
    print("SERVER ERROR:", str(e))
    return {"error": str(e)}, 500
@app.route("/")
def health():
    return "OK", 200
@app.route("/test")
def test():
    return {"server":"running"}
@app.route("/webhook/cyberbiz/order", methods=["POST"])
def cyberbiz_order():
    
    if not verify_signature(request):
        return "invalid signature", 403
        
    try:
        data = request.get_json(silent=True)
        print("WEBHOOK DATA:", data)

        return {"status": "ok"}, 200

    except Exception as e:
        print("ERROR:", str(e))
        return {"error": str(e)}, 500

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
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


    
   
  
'''
