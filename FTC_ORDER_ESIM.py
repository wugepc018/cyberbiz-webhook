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
import threading
from cyberbiz import send_order_email
from cyberbiz import generate_qrcode
from cyberbiz import check_and_close_order


AUTO_VENDOR = ["AUTO001", "AUTO002", "AUTO003"]
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
CYBERBIZ_USERNAME = os.environ.get("CYBERBIZ_USERNAME")
CYBERBIZ_SECRET = os.environ.get("CYBERBIZ_SECRET", "").encode()
CYBERBIZ_TOKEN = os.environ.get("CYBERBIZ_TOKEN")
FTC_API_KEY=os.environ.get("x_api_key")
VENDOR3_CUSTOMER_CODE = os.environ.get("VENDOR3_CUSTOMER_CODE") 
VENDOR3_CUSTOMER_AUTH = os.environ.get("VENDOR3_CUSTOMER_AUTH") 

logging.basicConfig(
    filename="/root/app/cyberbiz-webhook/logs/webhook.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

#FTC的訂購esim api        
def FTC_order_esim(order_id, planCode, email, trans_id , order_id_for_close_cyberbiz):
    FTC_SUBSCRIBE_API="https://zdfjzyhdcl.execute-api.ap-northeast-1.amazonaws.com/prod/v1/create"
    timestamp = str(int(time.time()))  
    

    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MOBILE_NUMBER, CUSTOMER_NAME, USE_DATE FROM orders WHERE Trans_id = ? AND status = 'pending'",
            (trans_id,)
        )
        row = cursor.fetchone()
        if not row:
            logging.error(f"找不到 trans_id={trans_id}")
            return

        mobile_number, customer_name, selectDate = row
        
        conn.commit()
    
    payload = {
        "type": "esim",
        "orderId": trans_id,
        "email": email,
        "buyerEmail":email,
        "buyerName": customer_name,
        "buyerMobile": mobile_number,
        "createDate":timestamp,
        "buyerAddress":None,
        "selectDate":selectDate,
        "selectLocation":None,
        "deliveryType":None,
        "orderLine":[
            {
                "orderLineId":"1",
                "productId":planCode,
                "quantity":1
            },
            
        ]
    }
    headers = {
    "Content-Type": "application/json",
    "x-api-key": FTC_API_KEY 
    }
    try:
        response=requests.post(FTC_SUBSCRIBE_API,json=payload,headers=headers,timeout=10)
        
        if response.json().get("code")=="200":
            logging.info(f"訂購請求成功 order_id={order_id} planCode={planCode} trans_id={trans_id}")
            
            with sqlite3.connect("orders.db", timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE orders SET status = 'processing' WHERE Trans_id = ?",
                    (trans_id,)
                )
                conn.commit()
            
            t = threading.Thread(target=poll_lpa, args=(trans_id, order_id_for_close_cyberbiz))
            t.daemon = True
            t.start()
        else:
            with sqlite3.connect("orders.db", timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE orders SET status = 'pending' WHERE Trans_id = ?",
                    (trans_id,)
                )
                conn.commit()
            logging.error(f"訂購請求失敗 {response.text}")
            
    except Exception as e:
        logging.error(f"呼叫供應商API失敗: {e}")

def query_lpa(trans_id):
    FTC_GET_ESIM_URL="https://zdfjzyhdcl.execute-api.ap-northeast-1.amazonaws.com/prod/v1/getInfo"
    
    payload={
        "orderId":trans_id
    }
    headers = {
    "Content-Type": "application/json",
    "x-api-key": FTC_API_KEY 
    }
    response=requests.post(FTC_GET_ESIM_URL, json=payload, headers=headers, timeout=10)
    data=response.json()
    if data.get("code")=="200":
        for order in data.get("data", []):
            for line in order.get("orderLine", []):
                product_id = line.get("productId")
                codes = line.get("code", [])
                cids = line.get("cid", [])
                logging.info(f"成功拿到esim資訊 product_id: {product_id} QRCODE_LPA: {codes} cid: {cids}")
                return product_id, codes, cids
                
    else:
        logging.info(f"沒有拿到esim資訊 {response.text}")
    
        
def poll_lpa(trans_id, order_id_for_close_cyberbiz):
    qrcode_list=[]
    for i in range(144):
        result = query_lpa(trans_id)

        if not result:
            logging.info(f"第{i+1}次查詢 result=None，sleep 600s")
            time.sleep(600)
            continue

        product_id, qrcodes_lpa, cid = result
        if not qrcodes_lpa or not cid:
            logging.info(f"第{i+1}次查詢 qrcode或cid為空，sleep 600s")
            time.sleep(600)
            continue
        lpa = qrcodes_lpa[0]
        cid = cid[0]
        qrcode_url=generate_qrcode(lpa)
        qrcode_list.append(qrcode_url)
        with sqlite3.connect("orders.db", timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT email, Title, order_id, qty_index, order_id_for_close_cyberbiz, line_items_id
                FROM orders 
                WHERE Trans_id = ? AND status = 'processing'
            """, (trans_id,))
            row = cursor.fetchone()
            if not row:
                logging.error(f"找不到 processing 訂單 {trans_id}")
                return
            email, full_title, order_id, qty_index, order_id_for_close_cyberbiz, line_items_id= row
            
            cursor.execute(
            "INSERT INTO CID_TABLE (CID, Trans_id) VALUES (?, ?)", (cid, trans_id)
            )
            cursor.execute(
            "UPDATE orders SET status='completed', qrcode=? WHERE Trans_id=?",
            (qrcode_url, trans_id)
            )
            conn.commit()
            cursor.execute("""
            SELECT COUNT(*) FROM orders
            WHERE order_id = ? AND line_items_id = ? AND status != 'completed'
        """, (order_id, line_items_id))
        
            remaining_in_item = cursor.fetchone()[0]
            if remaining_in_item == 0:
                
                cursor.execute("""SELECT qrcode, qty_index, Trans_id FROM orders
                    WHERE order_id = ? AND line_items_id = ?
                    ORDER BY qty_index ASC
                """, (order_id, line_items_id))
                
                qrcode_rows = cursor.fetchall()
                qrcode_list = [r[0] for r in qrcode_rows]
                trans_id_list = [r[2] for r in qrcode_rows]

                cid_list = []
                for tid in trans_id_list:
                    cursor.execute("SELECT CID FROM CID_TABLE WHERE Trans_id = ?", (tid,))
                    cid_row = cursor.fetchone()
                    cid_list.append(cid_row[0] if cid_row else None)
            
                logging.info(f"line_items_id={line_items_id} 全部完成，寄送含 {len(qrcode_list)} 張 QR code 的信")
                send_order_email(email, qrcode_list, full_title, cid_list=cid_list)
            else:
        
                logging.info(f"line_items_id={line_items_id} 尚有 {remaining_in_item} 筆未完成，等待中")

        logging.info(f"訂購esim完成 order_id={order_id} trans_id={trans_id}")
        check_and_close_order(order_id, order_id_for_close_cyberbiz)
        break
