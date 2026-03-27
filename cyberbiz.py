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

#LOG_PATH = "/root/app/cyberbiz-webhook/logs/webhook.log"
logging.basicConfig(
    filename="/root/app/cyberbiz-webhook/logs/webhook.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
AUTO_VENDOR = ["AUTO001", "AUTO002"]
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
CYBERBIZ_USERNAME = os.environ.get("CYBERBIZ_USERNAME")
CYBERBIZ_SECRET = os.environ.get("CYBERBIZ_SECRET", "").encode()
CYBERBIZ_TOKEN = os.environ.get("CYBERBIZ_TOKEN")
FTC_API_KEY=os.environ.get("x_api_key")

def init_db():
    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        print("DB PATH:", os.path.abspath("orders.db"))
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT,
        Created_AT TEXT,
        Trans_id TEXT,
        product_id TEXT,
        PlanCode TEXT,
        email TEXT,
        status TEXT,
        qrcode TEXT,
        qc TEXT,
        Title TEXT,
        qty_index INTEGER,
        QUANTITY INTEGER,
        order_id_for_close_cyberbiz INTEGER,
        NOTE TEXT,
        line_items_id TEXT,
        PRICE INTEGER,
        USE_DATE INTEGER,
        MOBILE_NUMBER INTEGER,
        CUSTOMER_NAME TEXT
        )
        """)
        cursor.execute("PRAGMA table_info(orders)")
        columns=[col[1] for col in cursor.fetchall()]
        
    
        if "NOTE" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN NOTE TEXT")

        if "line_items_id" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN line_items_id TEXT")
        
        if "USE_DATE" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN USE_DATE INTEGER")
        
        if "MOBILE_NUMBER" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN MOBILE_NUMBER INTEGER")
            
        if "Created_AT" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN Created_AT TEXT")
        
        if "CUSTOMER_NAME" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN CUSTOMER_NAME TEXT")
        
        if "PRICE" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN PRICE INTEGER")
            
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS CID_TABLE (
            CID TEXT,
            Trans_id TEXT
        )
        """)
        conn.commit()
        
init_db()
app = Flask(__name__)

@app.route("/")
def home():
    return "Webhook server running"

#接收Cyberbiz webhook傳來的訂單
@app.route("/webhook/cyberbiz/order", methods=["POST"])
def cyberbiz_order():

    data = request.json
    logging.info("Webhook received:")
    logging.info(json.dumps(data, indent=2, ensure_ascii=False))
    
    email = data.get("customer", {}).get("email")
    mobile_number = data.get("customer", {}).get("mobile")
    Customer_name = data.get("customer", {}).get("name")
    order_id = data.get("order_number")
    order_id_for_close_cyberbiz = data.get("id")
    note=data.get("note")
    created_at=data.get("created_at")

    logging.info(f"Order ID: {order_id}")
    logging.info(f"客戶email: {email}")
    
    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor=conn.cursor()
        line_items = data.get("line_items", [])
        tasks = []
        auto_count = 0
        cursor.execute("SELECT COUNT(*) FROM orders WHERE order_id = ?", (order_id,))
        existing_count = cursor.fetchone()[0]
        
        if existing_count > 0:
            logging.info(f"訂單 {order_id} 已存在，略過重複處理")
            return jsonify({"status": "ok"})

        for item in line_items:
            qc=item.get("qc")
            sku=item.get("sku")

            if qc not in AUTO_VENDOR:
                logging.info(f"訂單 {order_id} 含有非AUTO_VENDOR商品，整筆跳過")
                logging.info(f"訂單 {order_id} 需要人工處理")
                return jsonify({"status": "ok"})
            else:
                title=item.get("title")
                product_id=item.get("product_id")
                line_items_id=item.get("id")
                variant_title=item.get("variant_title")
                quantity=item.get("quantity")
                try:
                    price = item.get("price") or 0
                except (TypeError, ValueError):
                    price = 0
                logging.info(f"Product ID: {product_id}")
                logging.info(f"廠商編號: {qc}")
                logging.info(f"產品名稱: {title}")
                logging.info(f"產品類型: {variant_title}")
                logging.info(f"產品代號: {sku}")
                logging.info(f"備註欄位: {note}")
                full_title = f"{title} {variant_title}" if variant_title else title
                for i in range(quantity):
                    trans_id = str(uuid.uuid4()).replace("-", "")[:20]
                    auto_count += 1 
                    qty_index = existing_count + auto_count
                    today = datetime.datetime.now() #日期寫死 
                    use_date = int(today.timestamp())
                    cursor.execute(
                        """INSERT INTO orders 
                            (order_id, Created_AT, Trans_id, PlanCode, email, product_id, qc, 
                            status, qrcode, Title, qty_index, QUANTITY, order_id_for_close_cyberbiz, 
                            NOTE, line_items_id, PRICE, USE_DATE, MOBILE_NUMBER, CUSTOMER_NAME) 
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (order_id, created_at, trans_id, sku, email, product_id, qc,
                            "pending", None, full_title, qty_index, quantity, order_id_for_close_cyberbiz, 
                            note, line_items_id, price, use_date, mobile_number, Customer_name)
                    )
                    tasks.append((order_id, sku, email, trans_id, order_id_for_close_cyberbiz, qc))
                
        conn.commit()
        
    for task in tasks:
        order_id_, sku_, email_, trans_id_, close_id_, qc_ = task
        if qc_ == "AUTO001":
            order_esim(order_id_, sku_, email_, trans_id_, close_id_)
        elif qc_ == "AUTO002":
            FTC_order_esim(order_id_, sku_, email_, trans_id_, close_id_)
            
    return jsonify({
        "status": "ok",
    })
    
#RSP的訂購esim api
Base_URL="https://neware.biz"
def order_esim(order_id, planCode, email, trans_id , order_id_for_close_cyberbiz):
    RSP_SUBSCRIBE_API=f"{Base_URL}/openapi/esim/plan/subscribe"
    timestamp = str(int(time.time() * 1000))  
    raw = APP_ID + trans_id + timestamp + APP_SECRET
    ciphertext = hashlib.md5(raw.encode()).hexdigest()

    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET status = 'processing' WHERE Trans_id = ? AND status = 'pending'",
            (trans_id,)
        )
        conn.commit()
    
    payload = {
        "planCode": planCode,
        "qrcodeType": 0,
        "email": email
    }
    headers = {
        "Content-Type": "application/json",
        "AppId": APP_ID,
        "TransId": trans_id,
        "Timestamp": timestamp,
        "Ciphertext": ciphertext
    }
    try:
        response=requests.post(RSP_SUBSCRIBE_API,json=payload,headers=headers,timeout=10)
        
        if response.json().get("code")=="000":
            logging.info(f"訂購請求成功 order_id={order_id} planCode={planCode} trans_id={trans_id}")
        
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
            time.sleep(600)
            continue

        product_id, qrcodes_lpa, cid = result
        if not qrcodes_lpa or not cid:
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
def generate_qrcode(qrcodes_lpa):
    img = qrcode.make(qrcodes_lpa)
      
    imgByte=io.BytesIO()
    img.save(imgByte, format="PNG")
    imgByte.seek(0)

    return imgByte.read()
    
#接收供應商傳來的esim資訊
@app.route("/notify/esim/plan/subscribe", methods=["POST"])
def notify_esim():
    
    data=request.json
    logging.info("eSIM訂購通知收到:")
    logging.info(json.dumps(data, indent=2, ensure_ascii=False))
    trans_id=data.get("transId")
    result_code=data.get("resultCode")
    
    if result_code!="000":
        logging.error(f"trans_id{trans_id} 訂購失敗：{data.get('mesg')}")
        return jsonify({
            "code": "999",
            "mesg": "System Error"
        })
    
    esim_data=data.get("data", {})
    cid= str(esim_data.get("cid"))
    qrcode_type = esim_data.get("qrcodeType")
    qrcode = esim_data.get("qrcode")
    plan_code = esim_data.get("planCode")

    logging.info(f"transId: {trans_id}")
    logging.info(f"CID: {cid}")
    logging.info(f"qrcodeType: {qrcode_type}")
    logging.info(f"qrcode: {qrcode}")
    logging.info(f"transId: {trans_id}, CID: {cid}, planCode: {plan_code}")
    
    if qrcode_type == 1:
        # LPA 字串，用 qrserver 產生 QR Code 圖片
        qrcode_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={qrcode}"
    else:
        qrcode_url = qrcode
    
    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT email, Title, order_id, qty_index, order_id_for_close_cyberbiz, line_items_id
            FROM orders 
            WHERE Trans_id = ? AND status = 'processing'
        """, (trans_id,))
        
        row = cursor.fetchone()
        
        if not row:
            logging.error(f"找不到 trans_id={trans_id} 對應的訂單")
            return jsonify({"code": "999", "mesg": "Failed"})
        
        email, full_title, order_id, qty_index, order_id_for_close_cyberbiz, line_items_id= row

        cursor.execute(
            "UPDATE orders SET status='completed', qrcode=? WHERE Trans_id=?",
            (qrcode_url, trans_id)
        )
        cursor.execute(
            "INSERT INTO CID_TABLE (CID, Trans_id) VALUES (?, ?)", (cid, trans_id)
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
    return jsonify({"code": "000", "mesg": "success"})
    
def add_text_to_QRcode(qrcode_url, product_name, cid=None):
    if isinstance(qrcode_url, bytes):
        img=Image.open(io.BytesIO(qrcode_url))
    else:
        response = requests.get(qrcode_url)
        img = Image.open(io.BytesIO(response.content))
    
    header_height = 60
    footer_height = 40
    
    try:
        font_title = ImageFont.truetype("/root/app/NotoSansCJKtc-Regular.otf", 20)
        font_cid = ImageFont.truetype("/root/app/NotoSansCJKtc-Regular.otf", 16)
    except Exception:
        font_title = ImageFont.load_default()
        font_cid = ImageFont.load_default() 
        
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bbox = dummy_draw.textbbox((0, 0), product_name, font=font_title)
    text_width = bbox[2] - bbox[0] + 20  
    
    new_width = max(img.width, text_width)
    new_height = img.height + header_height + footer_height
    new_img = Image.new("RGB", (new_width, new_height), "white")
    new_img.paste(img, (0, header_height))

    draw=ImageDraw.Draw(new_img)
    draw.text((10, 10), f"{product_name}", fill="black",  font=font_title)
    
    if cid:
        draw.text((10, img.height + header_height + 10), f"CID: {cid}", fill="black", font=font_cid)
    
    img_byte=io.BytesIO()
    new_img.save(img_byte, format="PNG")
    img_byte.seek(0)
    
    return img_byte.read()

def send_order_email(to_email, qrcode_url_list, product_name, cid_list=None):
    
    from_email = "wuge.esim@gmail.com"
    app_password = os.environ.get("GMAIL_PASSWORD")
    pdf_path = "/root/app/cyberbiz-webhook/2026年版 ESIM 設定.pdf"
    try:
        server=smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(from_email,app_password)
        
            
        msg=MIMEMultipart()
        msg['Subject']=f"{product_name}（共{len(qrcode_url_list)}張）"
        msg['From']=from_email
        msg['To'] = to_email
        
        qrcode_html_blocks = ""
        for idx, _ in enumerate(qrcode_url_list):
            qrcode_html_blocks += f"""
            <p><strong>第 {idx+1} 張 QR Code：</strong></p>
            <img src="cid:qrcode_{idx}" style="width:220px;"><br><br>
            """
        
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">

        <p>你好</p>

        <p>請於收到信件 <strong>90日內</strong> 透過 Wi-Fi 或行動上網來安裝完畢，逾期會失效。</p>

        <p>⚠️ 請記得一個 QR CODE 只能給<strong>一個手機</strong>掃描，被掃過就無法再給其他手機安裝了<br>
        安裝時請記得手機需<strong>連接網路</strong>，關掉<strong>飛航模式</strong></p>

        <p><strong>安裝方式(1)：</strong>打開手機的信箱，長按本信件下面的 CODE，會有一個加入ESIM 可以進行安裝</p>
    
        <p><strong>安裝方式(2)：</strong>將QR CODE 存到手機相簿後，如附件說明進入照相機圖庫安裝</p>

        <p><strong>安裝方式(3)：</strong>於 設定 &gt; 行動服務，點選加入ESIM，掃描 QR CODE 畫面安裝</p>

        <p>安裝後會在 設定 &gt; 行動服務 中間的SIM 出現<strong>啟用中</strong>的SIM卡，代表已經安裝進手機了。不用再重複掃描QR CODE。<br>
        由於台灣是非覆蓋國家，啟用中會比較久是正常現象，請勿擔心。<br>
        安裝完畢出現無法啟用也是因為人還在台灣在非覆蓋國家的關係，不用理會。</p>

        <p>安裝完成後到國外再做行動數據的切換，開啟<strong>數據漫遊</strong>使用<br>
        🚫 請勿移除ESIM，移除後就無法補發也無法再重新安裝<br>
        回國後再把ESIM 做刪除掉，避免下次使用ESIM混到舊的</p>

        <p>安裝使用有什麼問題，請洽我們 吳哥舖客服帳號【LINE ID】<strong>@uup3894y</strong><br>
        由於QR CODE 為數位複製品，無法做退換，還請多加注意</p>
        <p>
        {qrcode_html_blocks}
        </p>
        <p>謝謝你</p>

        </body>
        </html>
        """
            
        msg.attach(MIMEText(body_html, "html"))
        with open(pdf_path, "rb") as f:
            pdf = MIMEApplication(f.read(), _subtype="pdf")
            pdf.add_header('Content-Disposition', 'attachment', filename="2026年版 ESIM 設定.pdf")
            msg.attach(pdf)

        for idx, qrcode_url in enumerate(qrcode_url_list):
            cid = cid_list[idx] if cid_list and idx < len(cid_list) else None
            img_data = add_text_to_QRcode(qrcode_url, f"{product_name}（{idx+1}）", cid=cid)
            img=MIMEImage(img_data)
            img.add_header("Content-ID", f"<qrcode_{idx}>")
            img.add_header("Content-Disposition", "inline")
            msg.attach(img)     
    
        server.send_message(msg)
        logging.info(f"Email sent for {product_name}，共 {len(qrcode_url_list)} 張 QR code")
        server.quit()
        
    except Exception as e:
        logging.info(f"Send email failed: {e}")
        
def check_and_close_order(order_id, order_id_for_close_cyberbiz):
    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM orders
            WHERE order_id = ? AND status != 'completed'
        """, (order_id,))
        
        remaining = cursor.fetchone()[0]
        if remaining > 0:
            logging.info(f"訂單 {order_id} 尚未完成，剩餘 {remaining} 筆")
           
            return
        else:
          
            logging.info(f"訂單 {order_id} 全部完成，準備結案")
            close_cyberbiz_order(order_id_for_close_cyberbiz)
        
def close_cyberbiz_order(order_id:int):
    
    url_base = "https://app-store-api.cyberbiz.io"
    url_path = f"/v1/orders/{order_id}/update_status"
    url = url_base + url_path
    x_date = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())
    payload = "status=closed"
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(payload.encode()).digest()).decode()
    
    logging.info(f"secret length: {len(CYBERBIZ_SECRET)}")
    logging.info(f"secret preview: {CYBERBIZ_SECRET[:5]}")
    headers = {
        "X-Date": x_date,
        "Digest": digest,
        "Authorization": f"Bearer {CYBERBIZ_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    logging.info(f"x_date: {x_date}")
    logging.info(f"digest: {digest}")
    for i in range(3):
        try:
            response = requests.put(url, headers=headers, data=payload, timeout=30)
            logging.info(f"Cyberbiz 結案成功: {response.text}")
            break
        except Exception as e:
            logging.error(f"第{i+1}次結案失敗: {e}")
            time.sleep(3)
    
@app.route("/orders")
def orders():
    order_id_query = request.args.get("order_id")  
    status_query = request.args.get("status")  
    title_query = request.args.get("title")  
    Vendor_query = request.args.get("vendor")  
    date_from = request.args.get("date_from")  
    date_to = request.args.get("date_to")  
    page = int(request.args.get("page", 1)) 
    per_page = 20                                
    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        sql = """
            SELECT o.order_id, o.Created_AT, o.PlanCode, o.email, o.status, o.qc, o.Title, c.CID, o.NOTE, o.PRICE
            FROM orders o
            LEFT JOIN CID_TABLE c ON o.Trans_id = c.Trans_id
            WHERE 1=1
        """
        params = []

        if order_id_query:
            sql += " AND o.order_id = ?"
            params.append(order_id_query)

        if status_query:
            sql += " AND o.status = ?"
            params.append(status_query)

        if title_query:
            sql += " AND o.Title LIKE ?"
            params.append(f"%{title_query}%")
            
        if Vendor_query:
            sql += " AND o.qc = ?"
            params.append(Vendor_query)
            
        if date_from:
            sql += " AND o.Created_AT >= ?"
            params.append(date_from)

        if date_to:
            sql += " AND o.Created_AT <= ?"
            params.append(date_to + "T23:59:59")  
            
        sql += " ORDER BY o.rowid DESC"
        count_sql = f"SELECT COUNT(*) FROM ({sql})"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        sql += " LIMIT ? OFFSET ?"
        params.append(per_page)
        params.append((page - 1) * per_page)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
     
    def build_url(p):
        args = {
            "order_id": order_id_query or "",
            "status": status_query or "",
            "title": title_query or "",
            "vendor": Vendor_query or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "page": p
        }
        return "/orders?" + "&".join(f"{k}={v}" for k, v in args.items() if v != "")

    pagination = f'<div style="margin:12px 0; font-size:13px;">共 {total} 筆　第 {page} / {total_pages} 頁　'
    if page > 1:
        pagination += f'<a href="{build_url(1)}" style="margin:0 3px; padding:2px 8px; border:1px solid #ccc; border-radius:3px; text-decoration:none;">«</a>'
        pagination += f'<a href="{build_url(page-1)}" style="margin:0 3px; padding:2px 8px; border:1px solid #ccc; border-radius:3px; text-decoration:none;">上一頁</a>'
    if page < total_pages:
        pagination += f'<a href="{build_url(page+1)}" style="margin:0 3px; padding:2px 8px; border:1px solid #ccc; border-radius:3px; text-decoration:none;">下一頁</a>'
        pagination += f'<a href="{build_url(total_pages)}" style="margin:0 3px; padding:2px 8px; border:1px solid #ccc; border-radius:3px; text-decoration:none;">»</a>'
    pagination += '</div>'
    
    html = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <title>訂單報表</title>
            <style>
                * {{ box-sizing: border-box; }}
                body {{ 
                    font-family: 'Segoe UI', Arial, sans-serif; 
                    padding: 28px 36px; 
                    background: #f7f8fa; 
                    color: #333;
                }}
                h2 {{ 
                    font-size: 20px; 
                    font-weight: 600; 
                    margin-bottom: 20px; 
                    color: #1a1a2e;
                }}
                table {{ 
                    border-collapse: collapse; 
                    width: 100%; 
                    table-layout: fixed;
                    background: #fff;
                    border-radius: 8px;
                    overflow: hidden;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
                }}
                th {{ 
                    background: #f0f2f5; 
                    color: #555;
                    font-size: 12px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    padding: 11px 14px; 
                    border: 1px solid #e2e5ea;
                    text-align: left;
                    white-space: nowrap;
                   
                }}
                td {{ 
                    padding: 10px 14px; 
                    font-size: 13px; 
                    border: 1px solid #e2e5ea;
                    color: #444;
                    vertical-align: top;
                    word-break: break-word;
                }}
                th:nth-child(1), td:nth-child(1)  {{ width: 105px; }}
                th:nth-child(2), td:nth-child(2)  {{ width: 170px; }}
                th:nth-child(3), td:nth-child(3)  {{ width: 90px; }}
                th:nth-child(4), td:nth-child(4)  {{ width: 160px; }}
                th:nth-child(5), td:nth-child(5)  {{ width: 185px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
                th:nth-child(6), td:nth-child(6)  {{ width: 55px; white-space: nowrap; }}
                th:nth-child(7), td:nth-child(7)  {{ width: 210px; }}
                th:nth-child(8), td:nth-child(8)  {{ width: 55px;  }}
                th:nth-child(9), td:nth-child(9)  {{ width: 85px; white-space: nowrap; }}
                th:nth-child(10), td:nth-child(10) {{ width: 85px; white-space: nowrap; }}
                th:nth-child(11), td:nth-child(11) {{ width: 120px; }}
                tbody tr:hover td {{ background: #f5f8ff; }}
                .completed {{ color: #1a9e5c; font-weight: 500; }}
                .processing {{ color: #d48800; font-weight: 500; }}
                .pending {{ color: #999; font-weight: 500; }}
            </style>
        </head>
        
        <body>
            <h2>訂單報表</h2>

            <form method="get" action="/orders" style="margin-bottom:20px;">
            
                <input type="text" name="order_id" placeholder="輸入訂單單號" 
                    value="{order_id_query if order_id_query else ''}"
                    style="padding:5px; width:200px;">
                    
                <input type="text" name="title" placeholder="輸入產品名稱" 
                    value="{title_query if title_query else ''}"
                    style="padding:5px; width:200px;">
                    
                <input type="text" name="vendor" placeholder="輸入廠商代號" 
                    value="{Vendor_query if Vendor_query else ''}"
                    style="padding:5px; width:200px;">
                    
                <select name="status" style="padding:5px;">
                    <option value="">全部狀態</option>
                    <option value="pending" { "selected" if status_query == 'pending' else '' }>Pending</option>
                    <option value="processing" { "selected" if status_query == 'processing' else '' }>Processing</option>
                    <option value="completed" { "selected" if status_query == 'completed' else '' }>Completed</option>
                </select>
                
                <input type="date" name="date_from"
                    value="{date_from or ''}"
                    style="padding:5px;">
                    
                <span>～</span>
                
                <input type="date" name="date_to"
                    value="{date_to or ''}"
                    style="padding:5px;">
                    
                <button type="submit">搜尋</button>
                <a href="/orders" style="padding:5px 12px; text-decoration:none; border:1px solid #ccc; border-radius:3px;">清除</a>
            </form>
            <table>
                <tr>
                    <th>訂購日期</th>
                    <th>e-mail</th>
                    <th>訂單單號</th>
                    <th>產品名稱</th>
                    <th>CID</th>
                    <th>數量</th>
                    <th>PlanCode</th>
                    <th>金額</th>
                    <th>廠商代號</th>
                    <th>狀態</th>
                    <th>備註</th>
                </tr>
        """
    for row in rows:
        order_id, create_at, plan_code, email, status, qc, title, cid, note, cost = row
        amount=1
        html += f"""
        <tr>
            <td>{create_at}</td>
            <td>{email}</td>
            <td>{order_id}</td>
            <td>{title}</td>
            <td>{cid}</td>
            <td>{amount}</td>
            <td>{plan_code}</td>
            <td>{cost}</td>
            <td>{qc}</td>
            <td class="{status}">{status}</td>
            <td>{note}</td>
        </tr>
        """

    html += f"</table>{pagination}</body></html>"
    return html

@app.route("/test_line_items")
def test_line_items():
    order_id_query = request.args.get("order_id")
    if not order_id_query:
        return "請提供 order_id，例如 /test_line_items?order_id=20263"

    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT line_items_id, status
            FROM orders
            WHERE order_id = ?
        """, (order_id_query,))
        rows = cursor.fetchall()
 

        if not rows:
            return f"訂單 {order_id_query} 找不到任何資料"

        line_item_ids = [r[0] for r in rows]
        statuses = [r[1] for r in rows]

        return f"""
        訂單: {order_id_query} <br>
        line_item_ids: {line_item_ids} <br>
        狀態: {statuses} <br>
        可以用這些 line_item_ids 測試 Cyberbiz API
        """
        
@app.route("/retry/<trans_id>")
def retry(trans_id):
    with sqlite3.connect("orders.db", timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT order_id_for_close_cyberbiz FROM orders WHERE Trans_id=?", (trans_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "找不到訂單"})
        close_id = row[0]
    
    t = threading.Thread(target=poll_lpa, args=(trans_id, close_id))
    t.daemon = True
    t.start()
    return jsonify({"status": "ok", "message": f"重新觸發 {trans_id}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)


