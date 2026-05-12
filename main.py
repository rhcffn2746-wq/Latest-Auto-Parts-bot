import os, re, requests
from flask import Flask, request, jsonify
import anthropic

app = Flask(__name__)

WHATSAPP_TOKEN    = os.environ["WHATSAPP_TOKEN"]
WHATSAPP_PHONE_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
VERIFY_TOKEN      = os.environ["WHATSAPP_VERIFY_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def load_inventory():
    path = os.path.join(os.path.dirname(__file__), "inventory.txt")
    try:
        with open(path, "r") as f:
            data = f.read().strip()
            if data and data != "placeholder":
                return data
    except Exception:
        pass
    return ""

INVENTORY_TEXT = load_inventory()
HAS_INVENTORY = len(INVENTORY_TEXT) > 100
print(f"Inventory loaded: {HAS_INVENTORY}")

BASE_SYSTEM = """你是 Latest Auto Parts Sdn Bhd 的 WhatsApp 客服 AI 助理。
讀懂顧客詢問的零件（品牌、型號、零件名稱），在庫存資料中搜尋，用友善的中文或英文回覆。
回覆格式：
- 有庫存：✅ 有貨！[零件] - 庫存:[數量]件，價格:[RM xxx 或 請聯絡報價]
- 缺貨：❌ 暫時缺貨，可留電話待貨通知
- 找不到：建議相容零件或請顧客提供更多資料
回覆簡短友善，不超過5行。
庫存格式：品牌|型號|零件名稱|庫存數量|售價"""

def search_inventory(query):
    if not HAS_INVENTORY:
        return ""
    tokens = [t for t in re.split(r'\s+', query.lower()) if len(t) > 1]
    results = []
    for line in INVENTORY_TEXT.split('\n'):
        score = sum(1 for t in tokens if t in line.lower())
        if score > 0:
            results.append((score, line))
    results.sort(key=lambda x: -x[0])
    return '\n'.join(l for _, l in results[:30])

def send_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    requests.post(url, headers=headers, json=payload)

def ask_claude(customer_message):
    relevant = search_inventory(customer_message)
    context = f"顧客訊息：{customer_message}\n\n相關庫存：\n{relevant or '（無匹配，請建議相容零件）'}"
    system = BASE_SYSTEM
    if HAS_INVENTORY:
        system += f"\n\n庫存資料：\n{INVENTORY_TEXT[:60000]}"
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": context}]
    )
    return response.content[0].text

@app.route("/webhook", methods=["GET"])
def verify():
    mode, token, challenge = request.args.get("hub.mode"), request.args.get("hub.verify_token"), request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    try:
        for msg in data["entry"][0]["changes"][0]["value"].get("messages", []):
            if msg["type"] == "text":
                reply = ask_claude(msg["text"]["body"])
                send_message(msg["from"], reply)
    except Exception as e:
        print(f"Error: {e}")
    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def home():
    return f"Latest Auto Parts Bot running! Inventory: {'✅' if HAS_INVENTORY else '⚠️ not loaded'}", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
