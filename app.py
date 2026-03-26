import os
import json
import random
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS
import anthropic
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
#  Anthropic Client
# ─────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─────────────────────────────────────────────
#  In-Memory Data Store (replace with DB in production)
# ─────────────────────────────────────────────
MARKET_DATA = {
    "crops": {
        "Rice":      {"unit": "kg",   "current": 45,  "min": 30,  "max": 60},
        "Corn":      {"unit": "kg",   "current": 22,  "min": 15,  "max": 35},
        "Sugarcane": {"unit": "ton",  "current": 2800,"min": 2200,"max": 3500},
        "Banana":    {"unit": "kg",   "current": 18,  "min": 12,  "max": 28},
        "Coconut":   {"unit": "pc",   "current": 12,  "min": 8,   "max": 20},
        "Cassava":   {"unit": "kg",   "current": 8,   "min": 5,   "max": 14},
        "Pineapple": {"unit": "pc",   "current": 25,  "min": 18,  "max": 40},
        "Mongo":     {"unit": "kg",   "current": 65,  "min": 45,  "max": 90},
    },
    "livestock": {
        "Cattle":    {"unit": "head", "current": 18000,"min": 14000,"max": 25000},
        "Carabao":   {"unit": "head", "current": 22000,"min": 18000,"max": 30000},
        "Hog":       {"unit": "kg",   "current": 185, "min": 150,  "max": 230},
        "Chicken":   {"unit": "kg",   "current": 145, "min": 110,  "max": 180},
        "Duck":      {"unit": "kg",   "current": 160, "min": 120,  "max": 200},
        "Goat":      {"unit": "head", "current": 3500,"min": 2800, "max": 5000},
    }
}

NOTIFICATIONS = []
MARKETPLACE_LISTINGS = [
    {
        "id": 1,
        "seller": "Juan dela Cruz",
        "location": "General Santos City",
        "product": "Rice",
        "quantity": 500,
        "unit": "kg",
        "price": 43,
        "contact": "09171234567",
        "posted": "2 hours ago",
        "verified": True,
    },
    {
        "id": 2,
        "seller": "Maria Santos",
        "location": "Koronadal City",
        "product": "Corn",
        "quantity": 2000,
        "unit": "kg",
        "price": 20,
        "contact": "09281234567",
        "posted": "5 hours ago",
        "verified": True,
    },
    {
        "id": 3,
        "seller": "Pedro Reyes",
        "location": "Kidapawan City",
        "product": "Banana",
        "quantity": 300,
        "unit": "kg",
        "price": 17,
        "contact": "09391234567",
        "posted": "1 day ago",
        "verified": False,
    },
]

PRICE_HISTORY = {}  # commodity -> list of {date, price}

def _generate_price_history(commodity, current_price, days=30):
    """Generate synthetic historical price data."""
    history = []
    price = current_price
    for i in range(days, 0, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        change = random.uniform(-0.05, 0.05)
        price = max(1, price * (1 + change))
        history.append({"date": date, "price": round(price, 2)})
    history.append({"date": datetime.now().strftime("%Y-%m-%d"), "price": current_price})
    return history

def _init_price_history():
    for category in ["crops", "livestock"]:
        for name, info in MARKET_DATA[category].items():
            PRICE_HISTORY[name] = _generate_price_history(name, info["current"])

_init_price_history()

# ─────────────────────────────────────────────
#  Background Price Simulator
# ─────────────────────────────────────────────
def _simulate_price_updates():
    """Randomly nudge prices every 30 seconds to mimic live data."""
    while True:
        time.sleep(30)
        for category in ["crops", "livestock"]:
            for name, info in MARKET_DATA[category].items():
                change = random.uniform(-0.03, 0.03)
                new_price = info["current"] * (1 + change)
                new_price = max(info["min"], min(info["max"], new_price))
                new_price = round(new_price, 2)
                old_price = info["current"]
                MARKET_DATA[category][name]["current"] = new_price

                # Auto-notification for big moves
                if abs(new_price - old_price) / old_price > 0.02:
                    direction = "▲ rose" if new_price > old_price else "▼ dropped"
                    NOTIFICATIONS.insert(0, {
                        "id": int(time.time() * 1000),
                        "title": f"{name} price alert",
                        "message": f"{name} {direction} to ₱{new_price:.2f}/{info['unit']}",
                        "time": datetime.now().strftime("%H:%M"),
                        "read": False,
                        "type": "price",
                    })
                    if len(NOTIFICATIONS) > 50:
                        NOTIFICATIONS.pop()

                # Update history
                today = datetime.now().strftime("%Y-%m-%d")
                if PRICE_HISTORY[name] and PRICE_HISTORY[name][-1]["date"] == today:
                    PRICE_HISTORY[name][-1]["price"] = new_price
                else:
                    PRICE_HISTORY[name].append({"date": today, "price": new_price})

threading.Thread(target=_simulate_price_updates, daemon=True).start()

# ─────────────────────────────────────────────
#  API Routes
# ─────────────────────────────────────────────

@app.route("/api/prices")
def get_prices():
    """Return all current market prices."""
    return jsonify(MARKET_DATA)


@app.route("/api/prices/<commodity>")
def get_commodity_price(commodity):
    """Return price info for a single commodity."""
    for category in ["crops", "livestock"]:
        if commodity in MARKET_DATA[category]:
            data = MARKET_DATA[category][commodity].copy()
            data["name"] = commodity
            data["category"] = category
            data["history"] = PRICE_HISTORY.get(commodity, [])
            return jsonify(data)
    return jsonify({"error": "Commodity not found"}), 404


@app.route("/api/forecast", methods=["POST"])
def ai_forecast():
    """Use Claude AI to forecast price trends."""
    data = request.json or {}
    commodity = data.get("commodity", "Rice")
    days = data.get("days", 7)

    # Build context from price history
    history = PRICE_HISTORY.get(commodity, [])[-14:]
    history_text = ", ".join([f"{h['date']}: ₱{h['price']}" for h in history])

    category = "crop" if commodity in MARKET_DATA["crops"] else "livestock"
    current_price = None
    for cat in ["crops", "livestock"]:
        if commodity in MARKET_DATA[cat]:
            current_price = MARKET_DATA[cat][commodity]["current"]
            unit = MARKET_DATA[cat][commodity]["unit"]
            break

    prompt = f"""You are an expert agricultural market analyst for the Philippines, specifically SOCCSKSARGEN region.

Commodity: {commodity} ({category})
Current price: ₱{current_price}/{unit}
Recent 14-day price history: {history_text}
Forecast horizon: {days} days

Based on:
- Historical price data provided
- Typical seasonal patterns for this commodity in Mindanao
- Supply/demand dynamics in local markets
- Post-harvest conditions and regional factors

Provide a concise forecast in this exact JSON format (no markdown, pure JSON):
{{
  "trend": "upward|downward|stable",
  "confidence": 0.0-1.0,
  "forecast_prices": [
    {{"day": 1, "price": 0.0}},
    ...up to {days} days
  ],
  "summary": "2-3 sentence plain-language summary",
  "key_factors": ["factor1", "factor2", "factor3"],
  "recommendation": "Buy now / Wait / Sell now / Hold"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        forecast = json.loads(raw.strip())
        forecast["commodity"] = commodity
        forecast["current_price"] = current_price
        forecast["unit"] = unit
        return jsonify(forecast)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def ai_chat():
    """General AI assistant for farming advice."""
    data = request.json or {}
    message = data.get("message", "")
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "No message provided"}), 400

    system_prompt = """You are AgriAI, a helpful assistant for Filipino farmers in the SOCCSKSARGEN region of Mindanao, Philippines.

You specialize in:
- Agricultural market prices and trends
- Crop and livestock management advice
- Post-harvest storage tips
- Market strategies to maximize farmer income
- Trading and selling guidance
- Seasonal planting calendars for Mindanao

Always respond in a friendly, practical tone. Use Philippine currency (₱/PHP).
Keep answers concise and actionable. When relevant, mention local markets like
General Santos City, Koronadal, Kidapawan, and Cotabato."""

    messages = history + [{"role": "user", "content": message}]

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=system_prompt,
            messages=messages
        )
        reply = response.content[0].text
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notifications")
def get_notifications():
    return jsonify(NOTIFICATIONS[:20])


@app.route("/api/notifications/mark-read", methods=["POST"])
def mark_notifications_read():
    for n in NOTIFICATIONS:
        n["read"] = True
    return jsonify({"status": "ok"})


@app.route("/api/marketplace")
def get_marketplace():
    return jsonify(MARKETPLACE_LISTINGS)


@app.route("/api/marketplace/list", methods=["POST"])
def add_listing():
    data = request.json or {}
    listing = {
        "id": int(time.time()),
        "seller": data.get("seller", "Anonymous"),
        "location": data.get("location", "Unknown"),
        "product": data.get("product", ""),
        "quantity": data.get("quantity", 0),
        "unit": data.get("unit", "kg"),
        "price": data.get("price", 0),
        "contact": data.get("contact", ""),
        "posted": "Just now",
        "verified": False,
    }
    MARKETPLACE_LISTINGS.insert(0, listing)
    return jsonify({"status": "ok", "listing": listing})


@app.route("/api/tips")
def get_tips():
    """Return educational farming tips."""
    tips = [
        {
            "category": "Storage",
            "icon": "🏚️",
            "title": "Proper Grain Storage",
            "content": "Store rice and corn in airtight containers at moisture levels below 14%. Use hermetic bags to extend shelf life up to 12 months and reduce post-harvest losses by up to 30%."
        },
        {
            "category": "Market Strategy",
            "icon": "📈",
            "title": "Time Your Sales",
            "content": "Avoid selling immediately after harvest when prices are lowest. If storage is available, wait 4–8 weeks post-harvest when supply drops and prices typically rise 15–25%."
        },
        {
            "category": "Crop Planning",
            "icon": "🌱",
            "title": "Diversify Your Crops",
            "content": "Plant a mix of staple crops (rice/corn) and high-value vegetables. Diversification reduces risk and ensures steady income throughout the year."
        },
        {
            "category": "Pricing",
            "icon": "💰",
            "title": "Know Your Break-Even Price",
            "content": "Calculate your cost of production per kg including seeds, fertilizer, labor, and transport. Never sell below your break-even point. Aim for at least 20% profit margin."
        },
        {
            "category": "Buyers",
            "icon": "🤝",
            "title": "Build Direct Buyer Relationships",
            "content": "Contact local restaurants, schools, and food processors directly. Cutting out middlemen can increase your net income by 20–40% on the same harvest."
        },
        {
            "category": "Seasons",
            "icon": "🌤️",
            "title": "SOCCSKSARGEN Planting Calendar",
            "content": "For Mindanao: Rice planting peaks in June–July (wet season) and November–December (dry season). Corn planting is best in October–November. Monitor PAGASA forecasts before planting."
        },
    ]
    return jsonify(tips)


# ─────────────────────────────────────────────
#  Frontend (Single-Page App served inline)
# ─────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgriAI – Market Intelligence</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Instrument+Sans:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0d1117;--surface:#161b22;--surface2:#21262d;--border:#30363d;
  --green:#23d18b;--green-dim:#1a9e68;--yellow:#f0a500;--red:#f85149;
  --blue:#58a6ff;--text:#e6edf3;--text-muted:#7d8590;
  --font-head:'Syne',sans-serif;--font-body:'Instrument Sans',sans-serif;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:var(--font-body);min-height:100vh;overflow-x:hidden;}
a{color:inherit;text-decoration:none;}

/* LAYOUT */
.shell{display:flex;min-height:100vh;}
.sidebar{width:240px;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;position:fixed;height:100vh;z-index:100;}
.main{margin-left:240px;flex:1;padding:32px;max-width:1200px;}

/* SIDEBAR */
.logo{padding:24px 20px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border);}
.logo-icon{width:36px;height:36px;background:var(--green);border-radius:8px;display:grid;place-items:center;font-size:18px;}
.logo-text{font-family:var(--font-head);font-weight:800;font-size:1.1rem;color:var(--text);}
.logo-text span{color:var(--green);}
nav{padding:16px 12px;flex:1;}
nav a{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;font-size:0.9rem;color:var(--text-muted);transition:all .15s;margin-bottom:2px;cursor:pointer;}
nav a:hover,nav a.active{background:var(--surface2);color:var(--text);}
nav a.active{border-left:3px solid var(--green);}
.nav-icon{font-size:1.1rem;width:20px;text-align:center;}
.sidebar-footer{padding:16px;border-top:1px solid var(--border);font-size:0.75rem;color:var(--text-muted);}
.notif-badge{margin-left:auto;background:var(--red);color:#fff;border-radius:99px;font-size:0.7rem;padding:1px 6px;font-weight:700;}

/* PAGES */
.page{display:none;animation:fadeIn .2s ease;}
.page.active{display:block;}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* PAGE HEADER */
.page-header{margin-bottom:28px;}
.page-header h1{font-family:var(--font-head);font-size:1.8rem;font-weight:800;}
.page-header p{color:var(--text-muted);margin-top:4px;font-size:0.9rem;}

/* STAT CARDS */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:32px;}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;}
.stat-label{font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;}
.stat-value{font-family:var(--font-head);font-size:1.6rem;font-weight:700;}
.stat-change{font-size:0.8rem;margin-top:4px;}
.up{color:var(--green);}
.down{color:var(--red);}

/* PRICE TABLE */
.price-section{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:28px;}
.price-section-header{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}
.price-section-header h2{font-family:var(--font-head);font-size:1rem;font-weight:700;}
.badge{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:3px 10px;font-size:0.75rem;color:var(--text-muted);}
table{width:100%;border-collapse:collapse;}
th{text-align:left;padding:10px 20px;font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);}
td{padding:12px 20px;border-bottom:1px solid var(--border);font-size:0.9rem;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:var(--surface2);}
.price-val{font-family:var(--font-head);font-weight:700;font-size:1rem;}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:600;}
.tag.crop{background:rgba(35,209,139,.15);color:var(--green);}
.tag.livestock{background:rgba(240,165,0,.15);color:var(--yellow);}
.forecast-btn{background:none;border:1px solid var(--border);color:var(--blue);padding:4px 12px;border-radius:6px;font-size:0.78rem;cursor:pointer;transition:all .15s;}
.forecast-btn:hover{background:var(--blue);color:#fff;}

/* FORECAST */
.forecast-panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:28px;}
.forecast-panel h2{font-family:var(--font-head);font-size:1.1rem;font-weight:700;margin-bottom:16px;}
.forecast-controls{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;}
select,input{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:8px 14px;border-radius:8px;font-family:var(--font-body);font-size:0.88rem;}
select:focus,input:focus{outline:none;border-color:var(--green);}
.btn{background:var(--green);color:#0d1117;border:none;padding:9px 20px;border-radius:8px;font-family:var(--font-head);font-weight:700;font-size:0.88rem;cursor:pointer;transition:opacity .15s;}
.btn:hover{opacity:.85;}
.btn.secondary{background:var(--surface2);color:var(--text);border:1px solid var(--border);}
.chart-wrap{position:relative;height:260px;}
.forecast-result{margin-top:20px;display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.forecast-box{background:var(--surface2);border-radius:10px;padding:16px;}
.forecast-box h3{font-size:0.78rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;}
.forecast-box p{font-size:0.92rem;line-height:1.5;}
.factors-list{list-style:none;display:flex;flex-direction:column;gap:4px;}
.factors-list li::before{content:"→ ";color:var(--green);}
.rec-chip{display:inline-block;padding:6px 14px;border-radius:99px;font-weight:700;font-size:0.88rem;}
.rec-buy{background:rgba(35,209,139,.15);color:var(--green);}
.rec-sell{background:rgba(248,81,73,.15);color:var(--red);}
.rec-wait{background:rgba(240,165,0,.15);color:var(--yellow);}
.rec-hold{background:rgba(88,166,255,.15);color:var(--blue);}

/* AI CHAT */
.chat-wrap{display:flex;flex-direction:column;height:520px;background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.chat-messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px;}
.msg{max-width:75%;padding:12px 16px;border-radius:12px;font-size:0.9rem;line-height:1.5;}
.msg.user{background:var(--green);color:#0d1117;align-self:flex-end;border-bottom-right-radius:4px;}
.msg.ai{background:var(--surface2);border:1px solid var(--border);align-self:flex-start;border-bottom-left-radius:4px;}
.msg.ai .sender{font-size:0.72rem;color:var(--green);font-weight:700;margin-bottom:4px;}
.chat-input-row{display:flex;gap:10px;padding:16px;border-top:1px solid var(--border);}
.chat-input{flex:1;background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:10px 16px;border-radius:8px;font-family:var(--font-body);font-size:0.9rem;resize:none;}
.chat-input:focus{outline:none;border-color:var(--green);}

/* NOTIFICATIONS */
.notif-list{display:flex;flex-direction:column;gap:10px;}
.notif-item{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 20px;display:flex;gap:14px;align-items:flex-start;}
.notif-item.unread{border-left:3px solid var(--green);}
.notif-dot{width:10px;height:10px;border-radius:50%;background:var(--green);margin-top:4px;flex-shrink:0;}
.notif-dot.read{background:var(--border);}
.notif-title{font-weight:600;margin-bottom:3px;}
.notif-msg{font-size:0.87rem;color:var(--text-muted);}
.notif-time{font-size:0.75rem;color:var(--text-muted);margin-top:4px;}
.notif-controls{margin-bottom:20px;display:flex;gap:10px;}

/* MARKETPLACE */
.listing-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;}
.listing-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;}
.listing-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;}
.listing-product{font-family:var(--font-head);font-size:1.2rem;font-weight:700;}
.listing-price{font-family:var(--font-head);color:var(--green);font-size:1.1rem;font-weight:700;}
.listing-meta{font-size:0.83rem;color:var(--text-muted);display:flex;flex-direction:column;gap:3px;margin-bottom:14px;}
.listing-qty{font-size:0.88rem;margin-bottom:14px;}
.listing-footer{display:flex;justify-content:space-between;align-items:center;}
.verified{color:var(--green);font-size:0.75rem;font-weight:600;}
.contact-btn{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:6px 14px;border-radius:6px;font-size:0.82rem;cursor:pointer;transition:all .15s;}
.contact-btn:hover{border-color:var(--green);color:var(--green);}
.add-listing-form{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:28px;}
.add-listing-form h2{font-family:var(--font-head);font-size:1.1rem;font-weight:700;margin-bottom:16px;}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
.form-group{display:flex;flex-direction:column;gap:6px;}
.form-group label{font-size:0.8rem;color:var(--text-muted);}
.form-group input,.form-group select{width:100%;}

/* TIPS */
.tips-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;}
.tip-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px;}
.tip-icon{font-size:2rem;margin-bottom:12px;}
.tip-cat{font-size:0.72rem;color:var(--green);text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin-bottom:6px;}
.tip-title{font-family:var(--font-head);font-size:1rem;font-weight:700;margin-bottom:10px;}
.tip-content{font-size:0.88rem;color:var(--text-muted);line-height:1.6;}

/* LOADING */
.loading{display:flex;gap:4px;align-items:center;padding:10px 16px;}
.dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:bounce .8s infinite;}
.dot:nth-child(2){animation-delay:.15s;}
.dot:nth-child(3){animation-delay:.3s;}
@keyframes bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-6px)}}

/* LIVE INDICATOR */
.live-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);margin-right:6px;animation:pulse 1.5s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* RESPONSIVE */
@media(max-width:768px){
  .sidebar{width:60px;}
  .logo-text,.nav-label{display:none;}
  .main{margin-left:60px;padding:16px;}
  .forecast-result{grid-template-columns:1fr;}
  .form-grid{grid-template-columns:1fr;}
}
</style>
</head>
<body>
<div class="shell">

<!-- SIDEBAR -->
<aside class="sidebar">
  <div class="logo">
    <div class="logo-icon">🌾</div>
    <div class="logo-text">Agri<span>AI</span></div>
  </div>
  <nav>
    <a class="active" onclick="showPage('dashboard')"><span class="nav-icon">📊</span><span class="nav-label">Dashboard</span></a>
    <a onclick="showPage('forecast')"><span class="nav-icon">📈</span><span class="nav-label">AI Forecast</span></a>
    <a onclick="showPage('chat')"><span class="nav-icon">🤖</span><span class="nav-label">AI Assistant</span></a>
    <a onclick="showPage('notifications')" id="nav-notif"><span class="nav-icon">🔔</span><span class="nav-label">Alerts</span><span class="notif-badge" id="badge" style="display:none">0</span></a>
    <a onclick="showPage('marketplace')"><span class="nav-icon">🏪</span><span class="nav-label">Marketplace</span></a>
    <a onclick="showPage('tips')"><span class="nav-icon">📚</span><span class="nav-label">Learn</span></a>
  </nav>
  <div class="sidebar-footer">AgriAI v1.0 · SOCCSKSARGEN</div>
</aside>

<!-- MAIN CONTENT -->
<main class="main">

  <!-- DASHBOARD -->
  <div class="page active" id="page-dashboard">
    <div class="page-header">
      <h1>Market Dashboard</h1>
      <p><span class="live-dot"></span>Live prices updated every 30 seconds</p>
    </div>
    <div class="stat-grid" id="stat-grid"></div>
    <div class="price-section">
      <div class="price-section-header">
        <h2>🌾 Crops</h2>
        <span class="badge" id="crop-count">Loading…</span>
      </div>
      <table><thead><tr><th>Commodity</th><th>Price (₱)</th><th>Unit</th><th>Range</th><th>Action</th></tr></thead>
      <tbody id="crop-table"></tbody></table>
    </div>
    <div class="price-section">
      <div class="price-section-header">
        <h2>🐄 Livestock</h2>
        <span class="badge" id="live-count">Loading…</span>
      </div>
      <table><thead><tr><th>Commodity</th><th>Price (₱)</th><th>Unit</th><th>Range</th><th>Action</th></tr></thead>
      <tbody id="live-table"></tbody></table>
    </div>
  </div>

  <!-- FORECAST -->
  <div class="page" id="page-forecast">
    <div class="page-header">
      <h1>AI Price Forecast</h1>
      <p>Powered by Claude · Historical patterns + seasonal analysis</p>
    </div>
    <div class="forecast-panel">
      <h2>Select Commodity</h2>
      <div class="forecast-controls">
        <select id="fc-commodity"><option>Rice</option><option>Corn</option><option>Sugarcane</option><option>Banana</option><option>Coconut</option><option>Cassava</option><option>Pineapple</option><option>Mongo</option><option>Cattle</option><option>Carabao</option><option>Hog</option><option>Chicken</option><option>Duck</option><option>Goat</option></select>
        <select id="fc-days"><option value="7">7 days</option><option value="14">14 days</option><option value="30">30 days</option></select>
        <button class="btn" onclick="runForecast()">Run AI Forecast</button>
      </div>
      <div class="chart-wrap"><canvas id="forecastChart"></canvas></div>
      <div class="forecast-result" id="forecast-result" style="display:none">
        <div class="forecast-box">
          <h3>Summary</h3>
          <p id="fc-summary"></p>
          <br>
          <h3>Recommendation</h3>
          <span class="rec-chip" id="fc-rec"></span>
        </div>
        <div class="forecast-box">
          <h3>Key Factors</h3>
          <ul class="factors-list" id="fc-factors"></ul>
        </div>
      </div>
    </div>
  </div>

  <!-- AI CHAT -->
  <div class="page" id="page-chat">
    <div class="page-header">
      <h1>AI Farming Assistant</h1>
      <p>Ask about prices, crop tips, market strategy, and more</p>
    </div>
    <div class="chat-wrap">
      <div class="chat-messages" id="chat-messages">
        <div class="msg ai"><div class="sender">AgriAI</div>Magandang araw! I'm your AgriAI assistant. Ask me anything about crop prices, farming tips, or market strategies for SOCCSKSARGEN. How can I help you today?</div>
      </div>
      <div class="chat-input-row">
        <textarea class="chat-input" id="chat-input" rows="2" placeholder="Type your question…" onkeydown="chatKeydown(event)"></textarea>
        <button class="btn" onclick="sendChat()">Send</button>
      </div>
    </div>
  </div>

  <!-- NOTIFICATIONS -->
  <div class="page" id="page-notifications">
    <div class="page-header">
      <h1>Price Alerts</h1>
      <p>Notifications when prices hit key thresholds</p>
    </div>
    <div class="notif-controls">
      <button class="btn secondary" onclick="markAllRead()">Mark All Read</button>
    </div>
    <div class="notif-list" id="notif-list">
      <div style="color:var(--text-muted);padding:40px;text-align:center">Waiting for price movements…</div>
    </div>
  </div>

  <!-- MARKETPLACE -->
  <div class="page" id="page-marketplace">
    <div class="page-header">
      <h1>Farmer Marketplace</h1>
      <p>Direct listings · No middlemen</p>
    </div>
    <div class="add-listing-form">
      <h2>Post a Listing</h2>
      <div class="form-grid">
        <div class="form-group"><label>Your Name</label><input id="ls-seller" placeholder="Juan dela Cruz"></div>
        <div class="form-group"><label>Location</label><input id="ls-location" placeholder="General Santos City"></div>
        <div class="form-group"><label>Commodity</label><select id="ls-product"><option>Rice</option><option>Corn</option><option>Banana</option><option>Coconut</option><option>Sugarcane</option><option>Cassava</option><option>Pineapple</option><option>Mongo</option><option>Hog</option><option>Chicken</option><option>Cattle</option><option>Carabao</option><option>Duck</option><option>Goat</option></select></div>
        <div class="form-group"><label>Unit</label><select id="ls-unit"><option>kg</option><option>ton</option><option>pc</option><option>head</option></select></div>
        <div class="form-group"><label>Quantity</label><input id="ls-qty" type="number" placeholder="500"></div>
        <div class="form-group"><label>Price per unit (₱)</label><input id="ls-price" type="number" placeholder="45"></div>
        <div class="form-group"><label>Contact Number</label><input id="ls-contact" placeholder="09171234567"></div>
      </div>
      <br>
      <button class="btn" onclick="postListing()">Post Listing</button>
    </div>
    <div class="listing-grid" id="listing-grid"></div>
  </div>

  <!-- TIPS -->
  <div class="page" id="page-tips">
    <div class="page-header">
      <h1>Educational Resources</h1>
      <p>Tips on storage, planning, and market strategy</p>
    </div>
    <div class="tips-grid" id="tips-grid"></div>
  </div>

</main>
</div>

<script>
const API = "";
let chatHistory = [];
let forecastChart = null;
let notifInterval = null;
let priceInterval = null;

// ── Navigation ──
function showPage(name) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll("nav a").forEach(a => a.classList.remove("active"));
  document.getElementById("page-" + name).classList.add("active");
  event.currentTarget.classList.add("active");
  if (name === "notifications") loadNotifications();
  if (name === "marketplace") loadMarketplace();
  if (name === "tips") loadTips();
}

// ── Prices ──
async function loadPrices() {
  const res = await fetch(API + "/api/prices");
  const data = await res.json();
  renderStatCards(data);
  renderTable("crop-table", data.crops, "crop");
  renderTable("live-table", data.livestock, "livestock");
  document.getElementById("crop-count").textContent = Object.keys(data.crops).length + " commodities";
  document.getElementById("live-count").textContent = Object.keys(data.livestock).length + " commodities";
}

function renderStatCards(data) {
  const all = {...data.crops, ...data.livestock};
  const entries = Object.entries(all).slice(0, 4);
  const html = entries.map(([name, info]) => {
    const pct = (((info.current - info.min) / (info.max - info.min)) * 100).toFixed(0);
    const isHigh = pct > 60;
    return `<div class="stat-card">
      <div class="stat-label">${name}</div>
      <div class="stat-value ${isHigh ? 'up' : 'down'}">₱${info.current.toLocaleString()}</div>
      <div class="stat-change ${isHigh ? 'up' : 'down'}">${isHigh ? '▲' : '▼'} ${pct}% of range · per ${info.unit}</div>
    </div>`;
  }).join("");
  document.getElementById("stat-grid").innerHTML = html;
}

function renderTable(id, data, type) {
  const rows = Object.entries(data).map(([name, info]) => {
    const pct = ((info.current - info.min) / (info.max - info.min) * 100).toFixed(0);
    const cls = pct > 60 ? "up" : pct < 40 ? "down" : "";
    return `<tr>
      <td>${name} <span class="tag ${type}">${type}</span></td>
      <td><span class="price-val ${cls}">₱${info.current.toLocaleString()}</span></td>
      <td>${info.unit}</td>
      <td style="color:var(--text-muted);font-size:.82rem">₱${info.min}–₱${info.max}</td>
      <td><button class="forecast-btn" onclick="goForecast('${name}')">Forecast →</button></td>
    </tr>`;
  }).join("");
  document.getElementById(id).innerHTML = rows;
}

function goForecast(name) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll("nav a").forEach(a => a.classList.remove("active"));
  document.getElementById("page-forecast").classList.add("active");
  document.getElementById("fc-commodity").value = name;
  runForecast();
}

// ── Forecast ──
async function runForecast() {
  const commodity = document.getElementById("fc-commodity").value;
  const days = parseInt(document.getElementById("fc-days").value);

  const btn = document.querySelector("#page-forecast .btn");
  btn.textContent = "Analyzing…";
  btn.disabled = true;

  // Load history for chart backdrop
  const hRes = await fetch(API + "/api/prices/" + commodity);
  const hData = await hRes.json();
  const history = hData.history || [];

  // Call AI
  const res = await fetch(API + "/api/forecast", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({commodity, days})
  });
  const fc = await res.json();
  btn.textContent = "Run AI Forecast";
  btn.disabled = false;

  if (fc.error) { alert("Error: " + fc.error); return; }

  // Render chart
  const histLabels = history.slice(-14).map(h => h.date.slice(5));
  const histPrices = history.slice(-14).map(h => h.price);
  const fcLabels = fc.forecast_prices.map(f => "D+" + f.day);
  const fcPrices = fc.forecast_prices.map(f => f.price);

  const ctx = document.getElementById("forecastChart").getContext("2d");
  if (forecastChart) forecastChart.destroy();
  forecastChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [...histLabels, ...fcLabels],
      datasets: [
        {label: "Historical", data: [...histPrices, ...Array(fcPrices.length).fill(null)],
         borderColor: "#58a6ff", backgroundColor: "rgba(88,166,255,.1)", tension: 0.4, pointRadius: 3},
        {label: "AI Forecast", data: [...Array(histPrices.length-1).fill(null), histPrices[histPrices.length-1], ...fcPrices],
         borderColor: "#23d18b", borderDash: [6,4], backgroundColor: "rgba(35,209,139,.08)", tension: 0.4, pointRadius: 3}
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {legend: {labels: {color: "#e6edf3"}}},
      scales: {
        x: {ticks: {color: "#7d8590"}, grid: {color: "#21262d"}},
        y: {ticks: {color: "#7d8590", callback: v => "₱" + v.toLocaleString()}, grid: {color: "#21262d"}}
      }
    }
  });

  // Show result cards
  document.getElementById("fc-summary").textContent = fc.summary;
  const recEl = document.getElementById("fc-rec");
  const recClass = {buy: "rec-buy", sell: "rec-sell", wait: "rec-wait", hold: "rec-hold"};
  const r = (fc.recommendation || "Hold").toLowerCase().split(" ")[0];
  recEl.className = "rec-chip " + (recClass[r] || "rec-hold");
  recEl.textContent = fc.recommendation;
  const fl = document.getElementById("fc-factors");
  fl.innerHTML = (fc.key_factors || []).map(f => `<li>${f}</li>`).join("");
  document.getElementById("forecast-result").style.display = "grid";
}

// ── Chat ──
async function sendChat() {
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  appendMsg(msg, "user");
  chatHistory.push({role: "user", content: msg});
  appendLoading();

  const res = await fetch(API + "/api/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({message: msg, history: chatHistory.slice(-10)})
  });
  const data = await res.json();
  removeLoading();
  const reply = data.reply || "Sorry, I couldn't get a response.";
  appendMsg(reply, "ai");
  chatHistory.push({role: "assistant", content: reply});
}

function appendMsg(text, role) {
  const box = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "msg " + role;
  if (role === "ai") div.innerHTML = `<div class="sender">AgriAI</div>${text}`;
  else div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function appendLoading() {
  const box = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "msg ai"; div.id = "loading-msg";
  div.innerHTML = `<div class="sender">AgriAI</div><div class="loading"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>`;
  box.appendChild(div); box.scrollTop = box.scrollHeight;
}

function removeLoading() {
  const el = document.getElementById("loading-msg");
  if (el) el.remove();
}

function chatKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
}

// ── Notifications ──
async function loadNotifications() {
  const res = await fetch(API + "/api/notifications");
  const data = await res.json();
  const list = document.getElementById("notif-list");
  if (!data.length) {
    list.innerHTML = `<div style="color:var(--text-muted);padding:40px;text-align:center">Waiting for price movements…</div>`;
    return;
  }
  list.innerHTML = data.map(n => `
    <div class="notif-item ${n.read ? "" : "unread"}">
      <div class="notif-dot ${n.read ? "read" : ""}"></div>
      <div>
        <div class="notif-title">${n.title}</div>
        <div class="notif-msg">${n.message}</div>
        <div class="notif-time">${n.time}</div>
      </div>
    </div>`).join("");
  const unread = data.filter(n => !n.read).length;
  const badge = document.getElementById("badge");
  if (unread > 0) { badge.style.display = ""; badge.textContent = unread; }
  else { badge.style.display = "none"; }
}

async function markAllRead() {
  await fetch(API + "/api/notifications/mark-read", {method: "POST"});
  loadNotifications();
  document.getElementById("badge").style.display = "none";
}

// ── Marketplace ──
async function loadMarketplace() {
  const res = await fetch(API + "/api/marketplace");
  const data = await res.json();
  document.getElementById("listing-grid").innerHTML = data.map(l => `
    <div class="listing-card">
      <div class="listing-header">
        <div class="listing-product">${l.product}</div>
        <div class="listing-price">₱${l.price}/${l.unit}</div>
      </div>
      <div class="listing-meta">
        <span>📍 ${l.location}</span>
        <span>👤 ${l.seller}</span>
        <span>🕐 ${l.posted}</span>
      </div>
      <div class="listing-qty">Available: <strong>${l.quantity.toLocaleString()} ${l.unit}</strong></div>
      <div class="listing-footer">
        <span class="verified">${l.verified ? "✓ Verified Seller" : "Unverified"}</span>
        <button class="contact-btn" onclick="alert('Contact: ${l.contact}')">📞 Contact</button>
      </div>
    </div>`).join("");
}

async function postListing() {
  const listing = {
    seller: document.getElementById("ls-seller").value,
    location: document.getElementById("ls-location").value,
    product: document.getElementById("ls-product").value,
    unit: document.getElementById("ls-unit").value,
    quantity: parseFloat(document.getElementById("ls-qty").value),
    price: parseFloat(document.getElementById("ls-price").value),
    contact: document.getElementById("ls-contact").value,
  };
  if (!listing.seller || !listing.quantity || !listing.price) { alert("Please fill all fields."); return; }
  await fetch(API + "/api/marketplace/list", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(listing)
  });
  loadMarketplace();
}

// ── Tips ──
async function loadTips() {
  const res = await fetch(API + "/api/tips");
  const tips = await res.json();
  document.getElementById("tips-grid").innerHTML = tips.map(t => `
    <div class="tip-card">
      <div class="tip-icon">${t.icon}</div>
      <div class="tip-cat">${t.category}</div>
      <div class="tip-title">${t.title}</div>
      <div class="tip-content">${t.content}</div>
    </div>`).join("");
}

// ── Polling ──
function startPolling() {
  loadPrices();
  priceInterval = setInterval(loadPrices, 30000);
  notifInterval = setInterval(async () => {
    const res = await fetch(API + "/api/notifications");
    const data = await res.json();
    const unread = data.filter(n => !n.read).length;
    const badge = document.getElementById("badge");
    if (unread > 0) { badge.style.display = ""; badge.textContent = unread; }
    else { badge.style.display = "none"; }
  }, 15000);
}

startPolling();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    print("=" * 55)
    print("  AgriAI Market Intelligence Platform")
    print("  http://localhost:5000")
    print("=" * 55)
    print("\nEnsure ANTHROPIC_API_KEY is set in your .env file.\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
