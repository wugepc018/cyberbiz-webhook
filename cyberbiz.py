from flask import Flask,jsonify,request
import json
import os
import requests
import hmac
import hashlib
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
import logging

#LOG_PATH = "/root/app/cyberbiz-webhook/logs/webhook.log"
logging.basicConfig(
    filename="/root/app/cyberbiz-webhook/logs/webhook.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
AUTO_VENDOR = ["AUTO001", "AUTO002"]
def init_db():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS orders")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT,
    product_id TEXT,
    PlanCode TEXT,
    email TEXT,
    status TEXT,
    qrcode TEXT,
    qc TEXT,
    Title TEXT
    )
    """)
    
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
    logging.info("Webhook received:")
    print(data)
    logging.info(json.dumps(data, indent=2, ensure_ascii=False))
    
    email = data.get("customer", {}).get("email")
    order_id = data.get("order_number")
    
    logging.info(f"Order ID: {order_id}")
    logging.info(f"客戶email: {email}")
    
    conn=sqlite3.connect("orders.db")
    cursor=conn.cursor()
    line_items = data.get("line_items", [])
    
    for item in line_items:
        qc=item.get("qc")
        sku=item.get("sku")
        if qc in AUTO_VENDOR:
            title=item.get("title")
            product_id=item.get("product_id")
            variant_title=item.get("variant_title")
            logging.info(f"Product ID: {product_id}")
            logging.info(f"廠商編號: {qc}")
            logging.info(f"產品名稱: {title}")
            logging.info(f"產品類型: {variant_title}")
            logging.info(f"產品代號: {sku}")
            cursor.execute(
                "INSERT INTO orders (order_id, PlanCode , email,product_id,qc,status, Title) VALUES (?,?,?,?,?,?)",
                (order_id, sku, email, product_id, qc, "pending",title)
            )
            order_esim(order_id, sku, email)
            
        else:
            product_id=item.get("product_id")
            logging.info(f"{product_id} :需要人工處理")
            
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "ok",
    })
    
#訂購esim
Base_URL="https://neware.biz"
def order_esim(order_id,planCode,email):
    RSP_SUBSCRIBE_API=f"{Base_URL}/openapi/esim/plan/subscribe"
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE orders SET status = 'processing' WHERE order_id = ? AND PlanCode = ? AND status = 'pending'",
        (order_id, planCode)
    )
    conn.commit()
    conn.close()
    payload = {
        "planCode": planCode,
        "qrcodeType": 0,
        "email": email
    }
    headers = {
        "Content-Type": "application/json",
    }
    try:
        response=requests.post(RSP_SUBSCRIBE_API,json=payload,headers=headers,timeout=10)
        if response.json().get("code")=="000":
            return jsonify({
            "message": "Order esim Request Send Success"
                }), 200 
        else:
            return jsonify({
            "message":  "Order esim Request Send Failed"
                }), 400 
    except Exception as e:
        logging.error(f"呼叫供應商API失敗: {e}")
        
@app.route("/notify/esim/plan/subscribe", methods=["POST"])
def notify_esim():
    data=request.json
    logging.info("eSIM訂購通知收到:")
    logging.info(json.dumps(data, indent=2, ensure_ascii=False))
    trans_id=data.get("transId")
    result_code=data.get("resultCode")
    if result_code!="000":
        logging.error(f"trans_id{trans_id} 訂購失敗：{data.get('mesg')}")
        return jsonify({"msg":"system error"})
    
    esim_data=data.get("data", {})
    cid= esim_data.get("cid")
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
    
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT email, Title, order_id 
        FROM orders 
        WHERE PlanCode = ? AND status = 'processing'
        ORDER BY rowid ASC
        LIMIT 1
    """, (plan_code,))
    
    row = cursor.fetchone()
    if not row:
        logging.error(f"找不到 plan_code {plan_code} 對應的訂單")
        return jsonify({"code": "999", "mesg": "Failed"})
    email, title, order_id = row

    cursor.execute(
        "UPDATE orders SET status='completed, qrcode= ? WHERE order_id = ? AND status = 'processing'",
        (qrcode_url, order_id)
    )

    conn.commit()
    conn.close()
    
    logging.info("訂購esim成功")
    send_order_email(email,qrcode,cid,title)
    return jsonify({"code": "000", "mesg": "success"})
    
def add_text_to_QRcode(qrcode_url, cid, product_name):
    qr_img_data, _ = urllib.request.urlretrieve(qrcode_url)
    img=Image.open(qr_img_data)
    
    header_height = 40
    footer_height = 40
    new_height=img.height + header_height + footer_height
    new_img=Image.new("RGB",(img.width, new_height), "white")
    new_img.paste(img, (0, header_height))
    
    draw=ImageDraw.Draw(new_img)
    
    try:
        font_title = ImageFont.truetype("/Users/user/Downloads/NotoSansCJKtc-Regular.otf", 20)
        font_cid = ImageFont.truetype("/System/Library/Fonts/STHeiti Light.ttc", 18)
    except Exception:
        font_title = ImageFont.load_default()
        font_cid = ImageFont.load_default()
        
    draw.text((10, img.height + header_height + 10), f"{cid}", fill="black" , font=font_cid)
    draw.text((10, 10), f"{product_name}", fill="black",  font=font_title)
    
    img_byte=io.BytesIO()
    new_img.save(img_byte, format="PNG")
    img_byte.seek(0)
    
    return img_byte.read()
def send_order_email(to_email,qrcode_url,cid,product_name):
    cid_list=[f"cid"]
    from_email = "carrine0976@gmail.com"
    app_password = "kdws jamt mhue hmxc"
    qrcode_url = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=HelloTest" #response["data"]["qrcode"]
    pdf_path = "/Users/user/Documents/GitHub/Automation_JOB/cyberbiz-webhook/2026年版 ESIM 設定.pdf"
    '''
    conn=sqlite3.connect("orders.db")
    cursor=conn.cursor()
    cursor.execute("SELECT title  FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        logging.error(f"Order {order_id} not found in DB.")
        return
    title=row
    '''
    try:
        server=smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(from_email,app_password)
        for i, cid in enumerate(cid_list):
            
            msg=MIMEMultipart()
            msg['Subject']=f"日本 5日每日2GB*2（{i+1}）"
            msg['From']=from_email
            msg['To'] = to_email
            
            body_html = """
            <html>
            <body style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

            <p>你好，</p>

            <p>請於收到信件 <strong>90日內</strong> 透過 Wi-Fi 或行動上網來安裝完畢，逾期會失效。</p>

            <p>記得一個 QR CODE 只能給<strong>一個手機掃描</strong>，被掃過就無法再給其他手機安裝了。<br>
            安裝時請記得手機需<strong>連接網路</strong>，關掉<strong>飛航模式</strong>安裝。</p>

            <p>安裝後會在 <strong>設定 &gt; 行動服務</strong> 中間的 SIM 出現「啟用中」的卡片，代表已經安裝進手機了，不用再重複掃描 QR CODE。<br>
            由於台灣是非覆蓋國家，啟用中會比較久是正常現象請勿擔心。<br>
            之後到國外再做行動數據的切換，開啟<strong>數據漫遊</strong>使用。</p>

            <p>⚠️ 請勿移除 ESIM，移除後就無法補發也無法再重新安裝。<br>
            回國後可以把 ESIM 做刪除，避免下次使用 ESIM 混到舊的。</p>

            <p>下列網址是安裝 eSIM 的方式，可以參考：<br>
            <a href="https://www.youtube.com/watch?v=VY47xtoHccg&t=8s">https://www.youtube.com/watch?v=VY47xtoHccg&t=8s</a></p>

            <p>使用有什麼問題，請洽我們 吳哥舖客服帳號【LINE ID】<strong>@uup3894y</strong></p>

            <p style="color: red;">由於 QR CODE 為數位複製品，無法做退換，還請多加注意。</p>
            
            <p>請掃描以下 QR Code 安裝您的 eSIM：</p>
            <img src="cid:qrcode" width="200" >
            
            <p>謝謝你</p>
            </body>
            </html>
            """
            msg.attach(MIMEText(body_html, "html"))
            with open(pdf_path, "rb") as f:
                pdf = MIMEApplication(f.read(), _subtype="pdf")
                pdf.add_header('Content-Disposition', 'attachment', filename="2026年版 ESIM 設定.pdf")
                msg.attach(pdf)
        
            img_data = add_text_to_QRcode(qrcode_url, cid, product_name)
            img=MIMEImage(img_data)
            img.add_header("Content-ID", "<qrcode>")
            img.add_header("Content-Disposition", "inline")
            msg.attach(img)     
        
            server.send_message(msg)
            logging.info(f"Email {i+1}sent!")

        server.quit()
        
    except Exception as e:
        print(f"Send email failed: {e}")

@app.route("/test-email")
def test_email():
    send_order_email()
    return "Email sent test"
#send_order_email(to_email,"ORD123456", "https://example.com/qrcode.png")

@app.route("/test-order-esim")
def test_order_esim():
    order_esim("TEST001", "PC10000000100090", "carrine0976@ymail.com")
    return "order_esim triggered"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)


