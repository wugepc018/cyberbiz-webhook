from flask import Flask,jsonify,request
import json
import os
import requests
import hmac
import hashlib
from flask import Flask, request, jsonify
import sqlite3
def init_db():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT,
    product_id TEXT,
    trans_id TEXT,
    email TEXT,
    status TEXT,
    qrcode TEXT,
    )
    """)
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN qc TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
init_db()
app = Flask(__name__)

@app.route("/")
def home():
    return "Webhook server running"

#接收Cyberbiz webhook傳來的訂單
@app.route("/webhook/cyberbiz/order", methods=["POST"])
def cyberbiz_order():

    data = request.json
    print("Webhook received:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    email = data.get("customer", {}).get("email")
    order_id = data.get("order_number")
    print("Order ID:", order_id)
    print(f"客戶email: {email}")
    
    line_items = data.get("line_items", [])
    for item in line_items:
        qc=item.get("qc")
        if qc=="AUTO001":
            product_id=item.get("product_id")
            print("Product ID:", product_id)
            print("廠商編號:", qc)
            
            conn=sqlite3.connect("orders.db")
            cursor=conn.cursor()
            cursor.execute(
                "INSERT INTO orders (order_id,email,product_id,qc,status) VALUES (?,?,?,?,?)",
                (order_id,email, product_id,qc,"pending")
            )
            
        else:
            print("需要人工處理")
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "ok",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


