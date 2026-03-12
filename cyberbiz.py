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
    qty_index INTEGER,
    order_id_for_close_cyberbiz
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
    order_id_for_close_cyberbiz = data.get("id")
    
    logging.info(f"Order ID: {order_id}")
    logging.info(f"客戶email: {email}")
    
    conn=sqlite3.connect("orders.db")
    cursor=conn.cursor()
    line_items = data.get("line_items", [])
    tasks = []
    auto_count = 0
    cursor.execute("SELECT COUNT(*) FROM orders WHERE order_id = ?", (order_id,))
    existing_count = cursor.fetchone()[0]

    for item in line_items:
        qc=item.get("qc")
        sku=item.get("sku")

        if qc not in AUTO_VENDOR:
            logging.info(f"訂單 {order_id} 含有非AUTO_VENDOR商品，整筆跳過")
            logging.info(f"訂單 {order_id} 需要人工處理")
            conn.close() 
            return jsonify({"status": "ok"})
        else:
            title=item.get("title")
            product_id=item.get("product_id")
            variant_title=item.get("variant_title")
            logging.info(f"Product ID: {product_id}")
            logging.info(f"廠商編號: {qc}")
            logging.info(f"產品名稱: {title}")
            logging.info(f"產品類型: {variant_title}")
            logging.info(f"產品代號: {sku}")
            trans_id = str(uuid.uuid4()).replace("-", "")[:20]
            auto_count += 1 
            qty_index = existing_count + auto_count
            full_title = f"{title} {variant_title}" if variant_title else title
            cursor.execute(
                "INSERT INTO orders (order_id, Trans_id, PlanCode, email, product_id, qc, status, Title, qty_index, order_id_for_close_cyberbiz) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (order_id, trans_id, sku, email, product_id, qc, "pending", full_title, qty_index , order_id_for_close_cyberbiz)
            )
            tasks.append((order_id, sku, email, trans_id, order_id_for_close_cyberbiz))
            
    conn.commit()
    conn.close()
    
    for task in tasks: 
        order_esim(*task)
        
    return jsonify({
        "status": "ok",
    })
    
#訂購esim
Base_URL="https://neware.biz"
def order_esim(order_id, planCode, email, trans_id , order_id_for_close_cyberbiz):
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
        SELECT email, Title, order_id, qty_index, order_id_for_close_cyberbiz 
        FROM orders 
        WHERE Trans_id = ? AND status = 'processing'
    """, (trans_id,))
    
    row = cursor.fetchone()
    
    if not row:
        logging.error(f"找不到 trans_id={trans_id} 對應的訂單")
        return jsonify({"code": "999", "mesg": "Failed"})
    
    email, full_title, order_id, qty_index, order_id_for_close_cyberbiz= row

    cursor.execute(
        "UPDATE orders SET status='completed', qrcode=? WHERE Trans_id=?",
        (qrcode_url, trans_id)
    )

    conn.commit()
    conn.close()
    
    logging.info(f"訂購esim成功 order_id={order_id} trans_id={trans_id}")

    send_order_email(email, qrcode_url, cid, full_title, qty_index, order_id, order_id_for_close_cyberbiz)
    return jsonify({"code": "000", "mesg": "success"})
    
def add_text_to_QRcode(qrcode_url, product_name):
    response = requests.get(qrcode_url)
    img = Image.open(io.BytesIO(response.content))
    
    header_height = 60
    footer_height = 40
    
    try:
        font_title = ImageFont.truetype("/root/app/NotoSansCJKtc-Regular.otf", 20)
    except Exception:
        font_title = ImageFont.load_default()
        
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bbox = dummy_draw.textbbox((0, 0), product_name, font=font_title)
    text_width = bbox[2] - bbox[0] + 20  
    
    new_width = max(img.width, text_width)
    new_height = img.height + header_height + footer_height
    new_img = Image.new("RGB", (new_width, new_height), "white")
    new_img.paste(img, (0, header_height))

    draw=ImageDraw.Draw(new_img)
    draw.text((10, 10), f"{product_name}", fill="black",  font=font_title)
    
    img_byte=io.BytesIO()
    new_img.save(img_byte, format="PNG")
    img_byte.seek(0)
    
    return img_byte.read()
def send_order_email(to_email, qrcode_url, cid, product_name,qty_index,order_id ,order_id_for_close_cyberbiz):
    
    from_email = "wuge.esim@gmail.com"
    app_password = "xbes bgfm sadp sidt"
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

        <p>謝謝你</p>

        </body>
        </html>
        """
        msg.attach(MIMEText(body_html, "html"))
        with open(pdf_path, "rb") as f:
            pdf = MIMEApplication(f.read(), _subtype="pdf")
            pdf.add_header('Content-Disposition', 'attachment', filename="2026年版 ESIM 設定.pdf")
            msg.attach(pdf)
    
        img_data = add_text_to_QRcode(qrcode_url, product_name)
        img=MIMEImage(img_data)
        img.add_header("Content-ID", "<qrcode>")
        img.add_header("Content-Disposition", "inline")
        msg.attach(img)     
    
        server.send_message(msg)
        logging.info(f"Email ({qty_index}) sent!")
        close_cyberbiz_order(order_id_for_close_cyberbiz)

        server.quit()
        
    except Exception as e:
        logging.info(f"Send email failed: {e}")


CYBERBIZ_USERNAME = "ekzL3c-xypTQ8GJfPi5boF2oPz5TE7xCnfwp8tvf0pY"
CYBERBIZ_SECRET = b"IltgWm2sNwJpoAOYJkT0V3bUI78nYX9HhSgykFe4_-E"
CYBERBIZ_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3NzE5OTU3MDcsInNob3BfaWQiOjI3NTU0LCJzaG9wX2RvbWFpbiI6Ind1Z2UuY3liZXJiaXouY28ifQ.t9BwXuJkJm0U3BIOwvEpfXi895uvnh_m68ZYvpw7UKo"
def close_cyberbiz_order(order_id:int):
    http_method = "PUT"
    url_base = "https://app-store-api.cyberbiz.io"
    url_path = f"/v1/orders/{order_id}/update_status"
    url = url_base + url_path
    x_date = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())
    rline = http_method + ' ' + url_path + ' HTTP/1.1'
    payload = "status=closed"
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(payload.encode()).digest()).decode()
    sig_str = "x-date: " + x_date + "\n" + rline + "\n" + "digest: " + digest
    dig = hmac.new(CYBERBIZ_SECRET, msg=sig_str.encode(), digestmod=hashlib.sha256).digest()
    sig = base64.b64encode(dig).decode()
    auth = f'hmac username="{CYBERBIZ_USERNAME}", algorithm="hmac-sha256", headers="x-date request-line digest", signature="{sig}"'
    logging.info(f"secret length: {len(CYBERBIZ_SECRET)}")
    logging.info(f"secret preview: {CYBERBIZ_SECRET[:5]}")
    headers = {
        "X-Date": x_date,
        "Digest": digest,
        "Authorization": f"Bearer {CYBERBIZ_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    logging.info(f"x_date: {x_date}")
    logging.info(f"rline: {rline}")
    logging.info(f"digest: {digest}")
    logging.info(f"sig_str: {sig_str}")
    logging.info(f"auth: {auth}")
    try:
        response = requests.put(url, headers=headers, data=payload, timeout=10)
        logging.info(f"Cyberbiz 結案 order_id={order_id} response={response.text}")
    except Exception as e:
        logging.error(f"Cyberbiz 結案失敗 order_id={order_id}: {e}")
    
@app.route("/test_close")
def test_close():
    close_cyberbiz_order(20051)
    return "done"
    
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
                <th>交易編號</th>
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
            <td>{trans_id}</td>
            <td class="{status}">{status}</td>
            <td>{qty_index}</td>
        </tr>
        """

    html += "</table></body></html>"
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)


