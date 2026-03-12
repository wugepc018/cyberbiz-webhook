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
import time
import uuid

#LOG_PATH = "/root/app/cyberbiz-webhook/logs/webhook.log"
logging.basicConfig(
    filename="/root/app/cyberbiz-webhook/logs/webhook.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
AUTO_VENDOR = ["AUTO001", "AUTO002"]
APP_ID = "xtH7XEyey9Mv"
APP_SECRET = "ECA021C324614BBC9CDE22BC3BC805AB"
def init_db():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS orders")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT,
    Trans_id TEXT,
    product_id TEXT,
    PlanCode TEXT,
    email TEXT,
    status TEXT,
    qrcode TEXT,
    qc TEXT,
    Title TEXT,
    qty_index INTEGER
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
            trans_id = str(uuid.uuid4()).replace("-", "")[:20]
            cursor.execute("SELECT COUNT(*) FROM orders WHERE order_id = ?", (order_id,))
            qty_index = cursor.fetchone()[0] + 1
            cursor.execute(
                "INSERT INTO orders (order_id, Trans_id, PlanCode, email, product_id, qc, status, Title, qty_index) VALUES (?,?,?,?,?,?,?,?,?)",
                (order_id, trans_id, sku, email, product_id, qc, "pending", title, qty_index)
            )
            order_esim(order_id, sku, email, trans_id)
            
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
def order_esim(order_id, planCode, email, trans_id):
    RSP_SUBSCRIBE_API=f"{Base_URL}/openapi/esim/plan/subscribe"
    timestamp = str(int(time.time() * 1000))  
    raw = APP_ID + trans_id + timestamp + APP_SECRET
    ciphertext = hashlib.md5(raw.encode()).hexdigest()

    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE orders SET status = 'processing' WHERE Trans_id = ? AND status = 'pending'",
        (trans_id,)
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
            conn = sqlite3.connect("orders.db")
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE orders SET status = 'pending' WHERE Trans_id = ?",
                (trans_id,)
            )
            conn.commit()
            conn.close()
            
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
        return jsonify({
            "code": "999",
            "mesg": "System Error"
        })
    
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
        SELECT email, Title, order_id, qty_index 
        FROM orders 
        WHERE Trans_id = ? AND status = 'processing'
    """, (trans_id,))
    
    row = cursor.fetchone()
    
    if not row:
        logging.error(f"找不到 trans_id={trans_id} 對應的訂單")
        return jsonify({"code": "999", "mesg": "Failed"})
    
    email, title, order_id, qty_index = row

    cursor.execute(
        "UPDATE orders SET status='completed', qrcode=? WHERE Trans_id=?",
        (qrcode_url, trans_id)
    )

    conn.commit()
    conn.close()
    
    logging.info(f"訂購esim成功 order_id={order_id} trans_id={trans_id}")

    send_order_email(email, qrcode, cid, title, qty_index)
    return jsonify({"code": "000", "mesg": "success"})
    
def add_text_to_QRcode(qrcode_url, cid, product_name):
    response = requests.get(qrcode_url)
    img = Image.open(io.BytesIO(response.content))
    
    header_height = 40
    footer_height = 40
    new_height=img.height + header_height + footer_height
    new_img=Image.new("RGB",(img.width, new_height), "white")
    new_img.paste(img, (0, header_height))
    
    draw=ImageDraw.Draw(new_img)
    
    try:
        font_title = ImageFont.truetype("/root/app/NotoSansCJKtc-Regular.otf", 20)
    except Exception:
        font_title = ImageFont.load_default()
        
        
    draw.text((10, 10), f"{product_name}", fill="black",  font=font_title)
    
    img_byte=io.BytesIO()
    new_img.save(img_byte, format="PNG")
    img_byte.seek(0)
    
    return img_byte.read()
def send_order_email(to_email, qrcode_url, cid, product_name,qty_index):
    
    from_email = "carrine0976@gmail.com"
    app_password = "kdws jamt mhue hmxc"
    pdf_path = "/root/app/cyberbiz-webhook/2026年版 ESIM 設定.pdf"
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
        
            
        msg=MIMEMultipart()
        msg['Subject']=f"{product_name}（{qty_index}）"
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
        logging.info(f"Email ({qty_index}) sent!")

        server.quit()
        
    except Exception as e:
        logging.info(f"Send email failed: {e}")

@app.route("/orders")
def orders():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT order_id, Trans_id, PlanCode, email, status, qc, Title, qty_index 
        FROM orders 
        ORDER BY rowid DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    html = """
    <html>
    <head>
        <meta charset="utf-8">
        <title>訂單報表</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ccc; padding: 8px; text-align: left; font-size: 13px; }
            th { background: #f0f0f0; }
            .completed { color: green; }
            .processing { color: orange; }
            .pending { color: gray; }
        </style>
    </head>
    <body>
        <h2>訂單報表</h2>
        <table>
            <tr>
                <th>訂單編號</th>
                <th>產品名稱</th>
                <th>PlanCode</th>
                <th>Email</th>
                <th>狀態</th>
                <th>第幾張</th>
            </tr>
    """

    for row in rows:
        order_id, trans_id, plan_code, email, status, qc, title, qty_index = row
        html += f"""
        <tr>
            <td>{order_id}</td>
            <td>{title}</td>
            <td>{plan_code}</td>
            <td>{email}</td>
            <td class="{status}">{status}</td>
            <td>{qty_index}</td>
        </tr>
        """

    html += "</table></body></html>"
    return html
@app.route("/test-email")
def test_email():
    send_order_email()
    return "Email sent test"
#send_order_email(to_email,"ORD123456", "https://example.com/qrcode.png")

@app.route("/test-order-esim")
def test_order_esim():
    trans_id = str(uuid.uuid4()).replace("-", "")[:20]
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute(
    "INSERT INTO orders (order_id, Trans_id, PlanCode, email, product_id, qc, status, Title, qty_index) VALUES (?,?,?,?,?,?,?,?,?)",
    ("TEST001", trans_id, "PC10000000100090", "carrine0976@ymail.com", "TEST_PRODUCT", "AUTO001", "pending", "測試商品", 1)
)
    conn.commit()
    conn.close()
    order_esim("TEST001", "PC10000000100090", "carrine0976@ymail.com", trans_id)
    return "order_esim triggered"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)


