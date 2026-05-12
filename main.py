import os, json, re, requests
from flask import Flask, request, jsonify
import anthropic

app = Flask(__name__)

# ── ENV ──────────────────────────────────────────────────────────────────────
WHATSAPP_TOKEN        = os.environ["WHATSAPP_TOKEN"]
WHATSAPP_PHONE_ID     = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
VERIFY_TOKEN          = os.environ["WHATSAPP_VERIFY_TOKEN"]
ANTHROPIC_API_KEY     = os.environ["ANTHROPIC_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── LOAD INVENTORY ───────────────────────────────────────────────────────────
def load_inventory():
    path = os.path.join(os.path.dirname(__file__), "inventory.txt")
    with open(path, "r") as f:
        return f.read()

INVENTORY_TEXT = load_inventory()

SYSTEM_PROMPT = f"""你是 Latest Auto Parts Sdn Bhd 的 WhatsApp 客服 AI 助理。

你的工作：
1. 讀懂顧客詢問的零件（品牌、型號、零件名稱）
2. 在庫存資料中搜尋
3. 用友善的中文或英文回覆（根據顧客用的語言）

回覆格式：
- 找到有庫存：✅ 有貨！[零件名稱] - 庫存: [數量] 件，價格: [RM xxx 或 請聯絡報價]
- 找到但缺貨：❌ 暫時缺貨：[零件名稱]，可留電話待貨通知
- 找不到完全符合：建議可能相容的零件，說明原因
- 完全找不到：誠實說找不到，建議顧客提供更多資料

庫存資料格式：品牌|型號|零件名稱|庫存數量|售價(空=未定價)

庫存資料：
{INVENTORY_TEXT[:80000]}
"""

# ── SEARCH INVENTORY ─────────────────────────────────────────────────────────
def search_inventory(query):
    query_lower = query.lower()
    tokens = re.split(r'\s+', query_lower)
    tokens = [t for t in tokens if len(t) > 1]
    
    lines = INVENTORY_TEXT.split('\n')
    results = []
    for line in lines:
        line_lower = line.lower()
        score = sum(1 for t in tokens if t in line_lower)
        if score > 0:
            results.append((score, line))
    
    results.sort(key=lambda x: -x[0])
    return '\n'.join(line for _, line in results[:30])

# ── SEND WHATSAPP MESSAGE ────────────────────────────────────────────────────
def send_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=payload)

# ── ASK CLAUDE ───────────────────────────────────────────────────────────────
def ask_claude(customer_message):
    # First do local search to narrow down results
    relevant = search_inventory(customer_message)
    
    context = f"""顧客訊息：{customer_message}

相關庫存搜尋結果（前30筆）：
{relevant if relevant else "（無直接匹配結果）"}

請根據以上庫存資料回覆顧客。"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}]
    )
    return response.content[0].text

# ── WEBHOOK ──────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    try:
        entry    = data["entry"][0]
        changes  = entry["changes"][0]
        value    = changes["value"]
        messages = value.get("messages", [])
        
        for msg in messages:
            if msg["type"] == "text":
                from_number = msg["from"]
                text        = msg["text"]["body"]
                
                # Send typing indicator feel
                reply = ask_claude(text)
                send_message(from_number, reply)
    except Exception as e:
        print(f"Error: {e}")
    
    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def home():
    return "Latest Auto Parts WhatsApp Bot is running! ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
