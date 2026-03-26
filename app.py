import json
import random
import time
from datetime import datetime, timedelta

import streamlit as st
import plotly.graph_objects as go
import anthropic

# ─────────────────────────────────────────────────────────────
#  Page config  (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AgriAI – Market Intelligence",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────
#  Custom CSS  (dark theme that mirrors the original design)
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Global */
html, body, [class*="css"] {
    font-family: 'Segoe UI', sans-serif;
    background-color: #0d1117;
    color: #e6edf3;
}
/* Sidebar */
section[data-testid="stSidebar"] {
    background: #161b22;
    border-right: 1px solid #30363d;
}
/* Metric cards */
div[data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 16px;
}
/* Headings */
h1, h2, h3 { color: #e6edf3; }
/* Buttons */
.stButton > button {
    background: #23d18b;
    color: #0d1117;
    border: none;
    border-radius: 8px;
    font-weight: 700;
}
.stButton > button:hover { opacity: 0.85; }
/* DataFrames */
.stDataFrame { border: 1px solid #30363d; border-radius: 8px; }
/* Chat messages */
.user-msg {
    background: #23d18b; color: #0d1117;
    padding: 12px 16px; border-radius: 12px;
    margin: 4px 0; max-width: 70%; float: right; clear: both;
}
.ai-msg {
    background: #21262d; border: 1px solid #30363d; color: #e6edf3;
    padding: 12px 16px; border-radius: 12px;
    margin: 4px 0; max-width: 70%; float: left; clear: both;
}
.ai-label { font-size: 0.72rem; color: #23d18b; font-weight: 700; margin-bottom: 4px; }
/* Listings */
.listing-card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 12px; padding: 16px; margin-bottom: 12px;
}
.tag-crop    { background: rgba(35,209,139,.15); color: #23d18b; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; }
.tag-live    { background: rgba(240,165,0,.15);  color: #f0a500; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; }
.notif-unread { border-left: 4px solid #23d18b; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
#  Anthropic client
# ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except KeyError:
        st.error("⚠️ ANTHROPIC_API_KEY not found. Add it to your Streamlit Cloud Secrets.")
        st.stop()
    return anthropic.Anthropic(api_key=api_key)

client = get_client()

# ─────────────────────────────────────────────────────────────
#  In-memory data  (kept in session_state so it persists
#  across reruns without requiring a DB)
# ─────────────────────────────────────────────────────────────
DEFAULT_MARKET = {
    "crops": {
        "Rice":      {"unit": "kg",   "current": 45,   "min": 30,   "max": 60},
        "Corn":      {"unit": "kg",   "current": 22,   "min": 15,   "max": 35},
        "Sugarcane": {"unit": "ton",  "current": 2800, "min": 2200, "max": 3500},
        "Banana":    {"unit": "kg",   "current": 18,   "min": 12,   "max": 28},
        "Coconut":   {"unit": "pc",   "current": 12,   "min": 8,    "max": 20},
        "Cassava":   {"unit": "kg",   "current": 8,    "min": 5,    "max": 14},
        "Pineapple": {"unit": "pc",   "current": 25,   "min": 18,   "max": 40},
        "Mongo":     {"unit": "kg",   "current": 65,   "min": 45,   "max": 90},
    },
    "livestock": {
        "Cattle":  {"unit": "head", "current": 18000, "min": 14000, "max": 25000},
        "Carabao": {"unit": "head", "current": 22000, "min": 18000, "max": 30000},
        "Hog":     {"unit": "kg",   "current": 185,   "min": 150,   "max": 230},
        "Chicken": {"unit": "kg",   "current": 145,   "min": 110,   "max": 180},
        "Duck":    {"unit": "kg",   "current": 160,   "min": 120,   "max": 200},
        "Goat":    {"unit": "head", "current": 3500,  "min": 2800,  "max": 5000},
    },
}

DEFAULT_LISTINGS = [
    {"id": 1, "seller": "Juan dela Cruz", "location": "General Santos City",
     "product": "Rice",   "quantity": 500,  "unit": "kg",   "price": 43,
     "contact": "09171234567", "posted": "2 hours ago", "verified": True},
    {"id": 2, "seller": "Maria Santos",   "location": "Koronadal City",
     "product": "Corn",   "quantity": 2000, "unit": "kg",   "price": 20,
     "contact": "09281234567", "posted": "5 hours ago", "verified": True},
    {"id": 3, "seller": "Pedro Reyes",    "location": "Kidapawan City",
     "product": "Banana", "quantity": 300,  "unit": "kg",   "price": 17,
     "contact": "09391234567", "posted": "1 day ago",   "verified": False},
]

def _gen_history(current, days=30):
    history, price = [], current
    for i in range(days, 0, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        price = max(1, price * (1 + random.uniform(-0.05, 0.05)))
        history.append({"date": date, "price": round(price, 2)})
    history.append({"date": datetime.now().strftime("%Y-%m-%d"), "price": current})
    return history

def _init_state():
    if "market" not in st.session_state:
        import copy
        st.session_state.market = copy.deepcopy(DEFAULT_MARKET)
    if "price_history" not in st.session_state:
        ph = {}
        for cat in ["crops", "livestock"]:
            for name, info in st.session_state.market[cat].items():
                ph[name] = _gen_history(info["current"])
        st.session_state.price_history = ph
    if "notifications" not in st.session_state:
        st.session_state.notifications = []
    if "listings" not in st.session_state:
        import copy
        st.session_state.listings = copy.deepcopy(DEFAULT_LISTINGS)
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

_init_state()

# ─────────────────────────────────────────────────────────────
#  Simulate live price nudge (called on each dashboard refresh)
# ─────────────────────────────────────────────────────────────
def simulate_price_update():
    market = st.session_state.market
    for cat in ["crops", "livestock"]:
        for name, info in market[cat].items():
            change = random.uniform(-0.03, 0.03)
            new_price = max(info["min"], min(info["max"], round(info["current"] * (1 + change), 2)))
            old_price = info["current"]
            market[cat][name]["current"] = new_price
            if abs(new_price - old_price) / old_price > 0.02:
                direction = "▲ rose" if new_price > old_price else "▼ dropped"
                st.session_state.notifications.insert(0, {
                    "id": int(time.time() * 1000),
                    "title": f"{name} price alert",
                    "message": f"{name} {direction} to ₱{new_price:.2f}/{info['unit']}",
                    "time": datetime.now().strftime("%H:%M"),
                    "read": False,
                    "type": "price",
                })
            # update history
            today = datetime.now().strftime("%Y-%m-%d")
            ph = st.session_state.price_history.get(name, [])
            if ph and ph[-1]["date"] == today:
                ph[-1]["price"] = new_price
            else:
                ph.append({"date": today, "price": new_price})

# ─────────────────────────────────────────────────────────────
#  Sidebar navigation
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding:8px 0 16px;">
        <div style="background:#23d18b;border-radius:8px;width:36px;height:36px;display:grid;place-items:center;font-size:20px;">🌾</div>
        <span style="font-size:1.2rem;font-weight:800;color:#e6edf3;">Agri<span style="color:#23d18b;">AI</span></span>
    </div>
    """, unsafe_allow_html=True)

    unread = sum(1 for n in st.session_state.notifications if not n["read"])
    alert_label = f"🔔 Alerts ({unread})" if unread else "🔔 Alerts"

    page = st.radio(
        "Navigation",
        ["📊 Dashboard", "📈 AI Forecast", "🤖 AI Assistant",
         alert_label, "🏪 Marketplace", "📚 Learn"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("AgriAI v1.0 · SOCCSKSARGEN")

# ─────────────────────────────────────────────────────────────
#  Helper: styled price table
# ─────────────────────────────────────────────────────────────
def render_price_table(data: dict, category: str):
    rows = []
    for name, info in data.items():
        pct = (info["current"] - info["min"]) / (info["max"] - info["min"]) * 100
        trend = "▲" if pct > 60 else ("▼" if pct < 40 else "–")
        rows.append({
            "Commodity": name,
            "Price (₱)": f"₱{info['current']:,.2f}",
            "Unit": info["unit"],
            "Range": f"₱{info['min']}–₱{info['max']}",
            "Trend": trend,
            "% of Range": f"{pct:.0f}%",
        })
    import pandas as pd
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────
#  PAGE: Dashboard
# ─────────────────────────────────────────────────────────────
if page == "📊 Dashboard":
    col_h, col_refresh = st.columns([4, 1])
    with col_h:
        st.title("📊 Market Dashboard")
        st.caption("🟢 Live prices – click Refresh to simulate update")
    with col_refresh:
        st.write("")
        if st.button("🔄 Refresh Prices"):
            simulate_price_update()
            st.rerun()

    market = st.session_state.market

    # Stat cards – top 4 commodities
    cols = st.columns(4)
    all_items = list(market["crops"].items()) + list(market["livestock"].items())
    for i, (name, info) in enumerate(all_items[:4]):
        pct = (info["current"] - info["min"]) / (info["max"] - info["min"]) * 100
        delta = f"{pct:.0f}% of range"
        cols[i].metric(label=f"🌾 {name}", value=f"₱{info['current']:,.2f}/{info['unit']}", delta=delta)

    st.markdown("---")

    # Crops table
    st.subheader("🌾 Crops")
    render_price_table(market["crops"], "crop")

    st.subheader("🐄 Livestock")
    render_price_table(market["livestock"], "livestock")

    # Quick-jump to forecast
    st.markdown("---")
    st.caption("💡 Tip: Switch to **AI Forecast** in the sidebar to get price predictions for any commodity.")

# ─────────────────────────────────────────────────────────────
#  PAGE: AI Forecast
# ─────────────────────────────────────────────────────────────
elif page == "📈 AI Forecast":
    st.title("📈 AI Price Forecast")
    st.caption("Powered by Claude · Historical patterns + seasonal analysis")

    market = st.session_state.market
    all_commodities = list(market["crops"].keys()) + list(market["livestock"].keys())

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        commodity = st.selectbox("Select Commodity", all_commodities)
    with col2:
        days = st.selectbox("Forecast Horizon", [7, 14, 30], format_func=lambda x: f"{x} days")
    with col3:
        st.write("")
        run = st.button("🤖 Run AI Forecast", use_container_width=True)

    # Show historical chart always
    history = st.session_state.price_history.get(commodity, [])[-14:]
    hist_dates  = [h["date"][-5:] for h in history]
    hist_prices = [h["price"] for h in history]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_dates, y=hist_prices,
        mode="lines+markers", name="Historical",
        line=dict(color="#58a6ff", width=2),
    ))
    fig.update_layout(
        paper_bgcolor="#161b22", plot_bgcolor="#161b22",
        font_color="#e6edf3", margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(bgcolor="#161b22"),
        xaxis=dict(gridcolor="#21262d"), yaxis=dict(gridcolor="#21262d"),
        height=300,
    )
    chart_placeholder = st.plotly_chart(fig, use_container_width=True, key="fc_chart")

    if run:
        cat = "crop" if commodity in market["crops"] else "livestock"
        info = market["crops"].get(commodity) or market["livestock"].get(commodity)
        current_price = info["current"]
        unit = info["unit"]

        history_14 = st.session_state.price_history.get(commodity, [])[-14:]
        history_text = ", ".join([f"{h['date']}: ₱{h['price']}" for h in history_14])

        prompt = f"""You are an expert agricultural market analyst for the Philippines, specifically SOCCSKSARGEN region.

Commodity: {commodity} ({cat})
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
  "confidence": 0.0,
  "forecast_prices": [{{"day": 1, "price": 0.0}}],
  "summary": "2-3 sentence plain-language summary",
  "key_factors": ["factor1", "factor2", "factor3"],
  "recommendation": "Buy now / Wait / Sell now / Hold"
}}
Generate up to {days} day entries in forecast_prices."""

        with st.spinner("🤖 Claude is analyzing market trends…"):
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw = response.content[0].text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                fc = json.loads(raw.strip())

                # Rebuild chart with forecast overlay
                fc_labels  = [f"D+{f['day']}" for f in fc["forecast_prices"]]
                fc_prices  = [f["price"] for f in fc["forecast_prices"]]
                bridge_x   = [hist_dates[-1]] + fc_labels
                bridge_y   = [hist_prices[-1]] + fc_prices

                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=hist_dates, y=hist_prices,
                    mode="lines+markers", name="Historical",
                    line=dict(color="#58a6ff", width=2),
                ))
                fig2.add_trace(go.Scatter(
                    x=bridge_x, y=bridge_y,
                    mode="lines+markers", name="AI Forecast",
                    line=dict(color="#23d18b", width=2, dash="dot"),
                ))
                fig2.update_layout(
                    paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                    font_color="#e6edf3", margin=dict(l=10, r=10, t=30, b=10),
                    legend=dict(bgcolor="#161b22"),
                    xaxis=dict(gridcolor="#21262d"), yaxis=dict(gridcolor="#21262d"),
                    height=320,
                )
                st.plotly_chart(fig2, use_container_width=True, key="fc_chart2")

                # Result cards
                c1, c2 = st.columns(2)
                with c1:
                    trend_colors = {"upward": "🟢", "downward": "🔴", "stable": "🟡"}
                    trend_icon = trend_colors.get(fc.get("trend", "stable"), "🟡")
                    st.markdown(f"""
                    <div style="background:#21262d;border-radius:10px;padding:16px;border:1px solid #30363d;">
                        <div style="font-size:.75rem;color:#7d8590;text-transform:uppercase;margin-bottom:8px;">Summary</div>
                        <p style="font-size:.9rem;line-height:1.5;">{trend_icon} {fc.get('summary','')}</p>
                        <br>
                        <div style="font-size:.75rem;color:#7d8590;text-transform:uppercase;margin-bottom:8px;">Recommendation</div>
                        <span style="background:rgba(35,209,139,.15);color:#23d18b;padding:6px 14px;border-radius:99px;font-weight:700;">
                            {fc.get('recommendation','Hold')}
                        </span>
                        <br><br>
                        <div style="font-size:.75rem;color:#7d8590;">Confidence: {fc.get('confidence',0)*100:.0f}%</div>
                    </div>
                    """, unsafe_allow_html=True)
                with c2:
                    factors_html = "".join([f"<li>→ {f}</li>" for f in fc.get("key_factors", [])])
                    st.markdown(f"""
                    <div style="background:#21262d;border-radius:10px;padding:16px;border:1px solid #30363d;">
                        <div style="font-size:.75rem;color:#7d8590;text-transform:uppercase;margin-bottom:8px;">Key Factors</div>
                        <ul style="list-style:none;padding:0;line-height:2;font-size:.9rem;">{factors_html}</ul>
                    </div>
                    """, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Forecast error: {e}")

# ─────────────────────────────────────────────────────────────
#  PAGE: AI Chat
# ─────────────────────────────────────────────────────────────
elif page == "🤖 AI Assistant":
    st.title("🤖 AI Farming Assistant")
    st.caption("Ask about prices, crop tips, market strategy, and more")

    SYSTEM = """You are AgriAI, a helpful assistant for Filipino farmers in the SOCCSKSARGEN region of Mindanao, Philippines.
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

    # Render chat history
    chat_container = st.container()
    with chat_container:
        if not st.session_state.chat_history:
            st.markdown("""
            <div class="ai-msg">
                <div class="ai-label">AgriAI</div>
                Magandang araw! I'm your AgriAI assistant. Ask me anything about crop prices,
                farming tips, or market strategies for SOCCSKSARGEN. How can I help you today?
            </div>
            <div style="clear:both"></div>
            """, unsafe_allow_html=True)
        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.markdown(f'<div class="user-msg">{msg["content"]}</div><div style="clear:both"></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="ai-msg"><div class="ai-label">AgriAI</div>{msg["content"]}</div><div style="clear:both"></div>', unsafe_allow_html=True)

    st.markdown("---")
    user_input = st.chat_input("Type your question… (e.g. What's the best time to sell rice?)")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.spinner("AgriAI is thinking…"):
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=600,
                    system=SYSTEM,
                    messages=st.session_state.chat_history[-12:],
                )
                reply = response.content[0].text
                st.session_state.chat_history.append({"role": "assistant", "content": reply})
            except Exception as e:
                st.session_state.chat_history.append({"role": "assistant", "content": f"Sorry, error: {e}"})
        st.rerun()

# ─────────────────────────────────────────────────────────────
#  PAGE: Notifications / Alerts
# ─────────────────────────────────────────────────────────────
elif "Alerts" in page:
    st.title("🔔 Price Alerts")
    st.caption("Auto-generated when prices move more than 2% in a single update")

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        if st.button("✅ Mark All Read"):
            for n in st.session_state.notifications:
                n["read"] = True
            st.rerun()

    notifs = st.session_state.notifications[:20]
    if not notifs:
        st.info("No alerts yet. Refresh the Dashboard a few times to trigger price movements.")
    else:
        for n in notifs:
            border = "border-left:4px solid #23d18b;" if not n["read"] else ""
            dot_color = "#23d18b" if not n["read"] else "#30363d"
            st.markdown(f"""
            <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px 20px;
                        margin-bottom:10px;display:flex;gap:14px;align-items:flex-start;{border}">
                <div style="width:10px;height:10px;border-radius:50%;background:{dot_color};margin-top:4px;flex-shrink:0;"></div>
                <div>
                    <div style="font-weight:600;">{n['title']}</div>
                    <div style="font-size:.87rem;color:#7d8590;">{n['message']}</div>
                    <div style="font-size:.75rem;color:#7d8590;margin-top:4px;">{n['time']}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
#  PAGE: Marketplace
# ─────────────────────────────────────────────────────────────
elif page == "🏪 Marketplace":
    st.title("🏪 Farmer Marketplace")
    st.caption("Direct listings · No middlemen")

    with st.expander("➕ Post a New Listing", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            ls_seller   = st.text_input("Your Name", placeholder="Juan dela Cruz")
            ls_location = st.text_input("Location",  placeholder="General Santos City")
            ls_product  = st.selectbox("Commodity",  ["Rice","Corn","Banana","Coconut","Sugarcane","Cassava","Pineapple","Mongo","Hog","Chicken","Cattle","Carabao","Duck","Goat"])
            ls_unit     = st.selectbox("Unit",        ["kg","ton","pc","head"])
        with c2:
            ls_qty      = st.number_input("Quantity",       min_value=1, value=100)
            ls_price    = st.number_input("Price per unit (₱)", min_value=0.0, value=45.0, step=0.5)
            ls_contact  = st.text_input("Contact Number", placeholder="09171234567")

        if st.button("📤 Post Listing"):
            if ls_seller and ls_contact and ls_qty and ls_price:
                st.session_state.listings.insert(0, {
                    "id": int(time.time()),
                    "seller": ls_seller, "location": ls_location,
                    "product": ls_product, "quantity": ls_qty,
                    "unit": ls_unit, "price": ls_price,
                    "contact": ls_contact, "posted": "Just now", "verified": False,
                })
                st.success("✅ Listing posted successfully!")
                st.rerun()
            else:
                st.error("Please fill in all required fields.")

    st.markdown("---")
    cols = st.columns(2)
    for i, listing in enumerate(st.session_state.listings):
        with cols[i % 2]:
            verified_badge = "✅ Verified Seller" if listing["verified"] else "⚠️ Unverified"
            st.markdown(f"""
            <div class="listing-card">
                <div style="display:flex;justify-content:space-between;margin-bottom:10px;">
                    <span style="font-size:1.2rem;font-weight:700;">{listing['product']}</span>
                    <span style="color:#23d18b;font-size:1.1rem;font-weight:700;">₱{listing['price']}/{listing['unit']}</span>
                </div>
                <div style="font-size:.83rem;color:#7d8590;line-height:1.7;">
                    📍 {listing['location']}<br>
                    👤 {listing['seller']}<br>
                    🕐 {listing['posted']}
                </div>
                <div style="margin:10px 0;font-size:.88rem;">
                    Available: <strong>{listing['quantity']:,} {listing['unit']}</strong>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#23d18b;font-size:.75rem;font-weight:600;">{verified_badge}</span>
                    <span style="background:#21262d;border:1px solid #30363d;border-radius:6px;
                                 padding:4px 12px;font-size:.82rem;cursor:pointer;">
                        📞 {listing['contact']}
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
#  PAGE: Learn / Tips
# ─────────────────────────────────────────────────────────────
elif page == "📚 Learn":
    st.title("📚 Educational Resources")
    st.caption("Tips on storage, planning, and market strategy")

    tips = [
        {"icon": "🏚️", "category": "Storage",         "title": "Proper Grain Storage",
         "content": "Store rice and corn in airtight containers at moisture levels below 14%. Use hermetic bags to extend shelf life up to 12 months and reduce post-harvest losses by up to 30%."},
        {"icon": "📈", "category": "Market Strategy",  "title": "Time Your Sales",
         "content": "Avoid selling immediately after harvest when prices are lowest. If storage is available, wait 4–8 weeks post-harvest when supply drops and prices typically rise 15–25%."},
        {"icon": "🌱", "category": "Crop Planning",    "title": "Diversify Your Crops",
         "content": "Plant a mix of staple crops (rice/corn) and high-value vegetables. Diversification reduces risk and ensures steady income throughout the year."},
        {"icon": "💰", "category": "Pricing",          "title": "Know Your Break-Even Price",
         "content": "Calculate your cost of production per kg including seeds, fertilizer, labor, and transport. Never sell below your break-even point. Aim for at least 20% profit margin."},
        {"icon": "🤝", "category": "Buyers",           "title": "Build Direct Buyer Relationships",
         "content": "Contact local restaurants, schools, and food processors directly. Cutting out middlemen can increase your net income by 20–40% on the same harvest."},
        {"icon": "🌤️", "category": "Seasons",          "title": "SOCCSKSARGEN Planting Calendar",
         "content": "For Mindanao: Rice planting peaks in June–July (wet season) and November–December (dry season). Corn planting is best in October–November. Monitor PAGASA forecasts before planting."},
    ]

    cols = st.columns(2)
    for i, tip in enumerate(tips):
        with cols[i % 2]:
            st.markdown(f"""
            <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:22px;margin-bottom:16px;">
                <div style="font-size:2rem;margin-bottom:12px;">{tip['icon']}</div>
                <div style="font-size:.72rem;color:#23d18b;text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin-bottom:6px;">{tip['category']}</div>
                <div style="font-family:sans-serif;font-size:1rem;font-weight:700;margin-bottom:10px;">{tip['title']}</div>
                <div style="font-size:.88rem;color:#7d8590;line-height:1.6;">{tip['content']}</div>
            </div>
            """, unsafe_allow_html=True)
