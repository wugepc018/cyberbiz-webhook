from flask import Flask,jsonify,request
import json
import os
import requests
import hmac
import hashlib
import base64
import urllib.request
from flask import Flask, request, jsonify
import sqlite3
import io
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urlencode
import logging
import time
import uuid
import datetime
import qrcode
import threading
import random
from cyberbiz import send_order_email
from cyberbiz import generate_qrcode
from cyberbiz import check_and_close_order


#LOG_PATH = "/root/app/cyberbiz-webhook/logs/webhook.log"
logging.basicConfig(
    filename="/root/app/cyberbiz-webhook/logs/webhook.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
AUTO_VENDOR = ["AUTO001", "AUTO002", "AUTO003"]
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
CYBERBIZ_USERNAME = os.environ.get("CYBERBIZ_USERNAME")
CYBERBIZ_SECRET = os.environ.get("CYBERBIZ_SECRET", "").encode()
CYBERBIZ_TOKEN = os.environ.get("CYBERBIZ_TOKEN")
FTC_API_KEY=os.environ.get("x_api_key")
VENDOR3_CUSTOMER_CODE = os.environ.get("VENDOR3_CUSTOMER_CODE") 
VENDOR3_CUSTOMER_AUTH = os.environ.get("VENDOR3_CUSTOMER_AUTH") 

def JOYTEL_order_esim(order_id, planCode, email, trans_id , order_id_for_close_cyberbiz):
    JOYTEL_SUBSCRIBE_API="https://api.joytel.vip/v2/customerApi/customerOrder"
    timestamp = int(int(time.time() * 1000))  

    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT CUSTOMER_NAME, MOBILE_NUMBER FROM orders WHERE Trans_id = ?", (trans_id,))
        row = cursor.fetchone()  
        customer_name, mobile_number = row
        cursor.execute("UPDATE orders SET status = 'processing' WHERE Trans_id = ?", (trans_id,))
        conn.commit()
       
    now_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    random_6 = str(random.randint(100000, 999999))
    orderTid = str(VENDOR3_CUSTOMER_CODE) + now_str + random_6
    
    item_list = [{"productCode": planCode, "quantity": 1}]
    autoGraph=generate_vendor3_sign(VENDOR3_CUSTOMER_CODE, VENDOR3_CUSTOMER_AUTH, 5, orderTid, customer_name, mobile_number, timestamp, item_list)
    
    payload = {
        "customerCode": VENDOR3_CUSTOMER_CODE,
        "orderTid":orderTid,
        "type": 5,
        "receiveName": customer_name,
        "phone": mobile_number,
        "timestamp": timestamp,
        "autoGraph": autoGraph,
        "email": email,
        "itemList": [
            {
                "productCode": planCode,
                "quantity": 1
            }
        ]
    }  
    headers = {
        "Content-Type": "application/json",
        
    }
    try:
        response=requests.post(JOYTEL_SUBSCRIBE_API,json=payload,headers=headers,timeout=10)
        
        if response.json().get("code")==1:
            logging.info(f"訂購請求成功 order_id={order_id} planCode={planCode} trans_id={trans_id}")
            with sqlite3.connect("orders.db", timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE orders SET status = 'processing' WHERE Trans_id = ?",
                    (trans_id,)
                )
                conn.commit()
            orderCode=response.json().get("data").get("orderCode")
            orderTid=response.json().get("data").get("orderTid")
            t = threading.Thread(target=poll_joytel, args=(trans_id, orderTid, order_id_for_close_cyberbiz, orderCode))
            t.daemon = True
            t.start()
                
        else:
            logging.error(f"供應商回應失敗 code={response.json().get('code')} 內容={response.text}") 
            with sqlite3.connect("orders.db", timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE orders SET status = 'pending' WHERE Trans_id = ?",
                    (trans_id,)
                )
                conn.commit()
            
    except Exception as e:
        logging.error(f"呼叫供應商API失敗: {e}")

def generate_vendor3_sign(customer_code, customer_auth, type_, order_tid, receive_name, phone, timestamp, item_list):
    item_str = ""
    for item in item_list:
        item_str += str(item["productCode"]) + str(item["quantity"])
    
    raw = (
        str(customer_code) +   # "test001"
        str(customer_auth) +   # "abcdefj"  ← 只用來算sign，不放payload
        "" +                   # warehouse 空字串
        str(type_) +           
        str(order_tid) +       # 你的訂單號
        str(receive_name) +    # 客戶名稱
        str(phone) +           # 電話
        str(timestamp) +       # 時間戳
        item_str               # "esim615xxxx11esim615xxxx21"
    )
    
    return hashlib.sha1(raw.encode()).hexdigest()
def JOYEL_query_QrCode(orderCode,orderTid):
    JOYTEL_query_API="https://api.joytel.vip/v2/customerApi/customerOrder/query"
    timestamp = int(int(time.time() * 1000)) 
    
    raw = (
        str(VENDOR3_CUSTOMER_CODE) +
        str(VENDOR3_CUSTOMER_AUTH) +
        str(orderCode) +           
        str(orderTid) +
        str(timestamp)
    )
    autoGraph = hashlib.sha1(raw.encode()).hexdigest()
    payload={
        
        "customerCode": VENDOR3_CUSTOMER_CODE,
        "timestamp": timestamp,
        "orderTid":orderTid,
        "autoGraph": autoGraph,
        "orderCode": orderCode

    }
    headers = {
        "Content-Type": "application/json",
        
    }
    try:
        response = requests.post(JOYTEL_query_API, json=payload, headers=headers, timeout=10)
        data = response.json()
        logging.info(f"JOYTEL 查詢回應: {response.text}")
        
        if data.get("code") == 0:
            order_data = data.get("data", {})
            status = order_data.get("status")
            
            if status == 4:  # 已發貨，可以拿 qrCode
                item_list = order_data.get("itemList", [])
                for item in item_list:
                    sn_list = item.get("snList", [])
                    for sn in sn_list:
                        qr_code = sn.get("qrCode")
                        sn_code = sn.get("snCode")  # 這個就是 CID
                        if qr_code:
                            logging.info(f"JOYTEL 拿到 qrCode: {qr_code} snCode: {sn_code}")
                            return qr_code, sn_code
            else:
                logging.info(f"JOYTEL 訂單狀態: {status}，尚未發貨")
                return None
    except Exception as e:
        logging.error(f"JOYTEL 查詢失敗: {e}")
        return None
    
def poll_joytel(trans_id, orderTid, order_id_for_close_cyberbiz, orderCode):
    for i in range(144):
        result = JOYEL_query_QrCode(orderCode, orderTid)
        
        if not result:
            logging.info(f"第{i+1}次查詢 JOYTEL，尚未完成，sleep 600s")
            time.sleep(600)
            continue
        
        qr_code, sn_code = result
        
        # 產生 qrcode 圖片
        qrcode_img = generate_qrcode(qr_code)
        
        with sqlite3.connect("orders.db", timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT email, Title, order_id, qty_index, order_id_for_close_cyberbiz, line_items_id
                FROM orders WHERE Trans_id = ? AND status = 'processing'
            """, (trans_id,))
            row = cursor.fetchone()
            if not row:
                logging.error(f"找不到 processing 訂單 {trans_id}")
                return
            email, full_title, order_id, qty_index, order_id_for_close_cyberbiz, line_items_id = row
            
            cursor.execute("INSERT INTO CID_TABLE (CID, Trans_id) VALUES (?, ?)", (sn_code, trans_id))
            cursor.execute("UPDATE orders SET status='completed', qrcode=? WHERE Trans_id=?", (qrcode_img, trans_id))
            conn.commit()
            
            cursor.execute("""
                SELECT COUNT(*) FROM orders
                WHERE order_id = ? AND line_items_id = ? AND status != 'completed'
            """, (order_id, line_items_id))
            remaining = cursor.fetchone()[0]
            
            if remaining == 0:
                cursor.execute("""
                    SELECT qrcode, qty_index, Trans_id FROM orders
                    WHERE order_id = ? AND line_items_id = ? ORDER BY qty_index ASC
                """, (order_id, line_items_id))
                qrcode_rows = cursor.fetchall()
                qrcode_list = [r[0] for r in qrcode_rows]
                trans_id_list = [r[2] for r in qrcode_rows]
                
                cid_list = []
                for tid in trans_id_list:
                    cursor.execute("SELECT CID FROM CID_TABLE WHERE Trans_id = ?", (tid,))
                    cid_row = cursor.fetchone()
                    cid_list.append(cid_row[0] if cid_row else None)
                
                send_order_email(email, qrcode_list, full_title, cid_list=cid_list)
            
        logging.info(f"JOYTEL 訂購完成 order_id={order_id} trans_id={trans_id}")
        check_and_close_order(order_id, order_id_for_close_cyberbiz)
        break