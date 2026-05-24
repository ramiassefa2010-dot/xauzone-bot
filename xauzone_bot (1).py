"""
╔══════════════════════════════════════════════════════════════╗
║          XauZone99Bot — FINAL VERSION 5.0                    ║
║    Pure Price Action · High Probability Setups               ║
║    Gold XAU/USD + EUR/USD · Full Trade Management            ║
║    Built for Rami                                            ║
╚══════════════════════════════════════════════════════════════╝

TRADE MANAGEMENT:
  Entry  → place trade
  1:1    → move SL to breakeven
  TP1    → 1:2 close majority
  TP2    → 1:3 close rest
  TP3    → 1:5 A+ setups only (runner)
"""

import requests
import time
import json
import os
from datetime import datetime
import pytz

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN   = "8901088980:AAH_0UoolFjUfj3Gv0opwbMxzqpe5Ia9H6A"
CHAT_ID     = "6538381591"
EAT         = pytz.timezone("Africa/Nairobi")
CHECK_EVERY = 180        # 3 minutes
PROXIMITY   = 4.0        # $4 proximity to level
COOLDOWN    = 300        # 5 min cooldown per level
QUIET_START = 21         # quiet after 9pm EAT
QUIET_END   = 7          # quiet before 7am EAT
LOG_FILE    = "trade_journal.json"
VERSION     = "5.0"

# High impact news (MM-DD) — update monthly
NEWS_EVENTS = {
    "05-23": "PMI Flash",
    "06-04": "NFP",
    "06-11": "US CPI",
    "06-12": "FOMC",
    "06-18": "FOMC Minutes",
    "06-25": "GDP",
    "07-03": "NFP",
    "07-10": "US CPI",
    "07-29": "FOMC",
    "08-01": "NFP",
    "08-13": "US CPI",
}

# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════
state = {
    "gold_price": None, "gold_prev": None,
    "eur_price":  None, "eur_prev":  None,
    "dxy_price":  None, "dxy_prev":  None,
    "gold_h1": [], "gold_h4": [],
    "eur_h1":  [], "eur_h4":  [],
    "dxy_h1":  [],
    "asian_high_gold": None, "asian_low_gold": None,
    "asian_high_eur":  None, "asian_low_eur":  None,
    "london_open_gold": None, "ny_open_gold": None,
    "london_open_eur":  None, "ny_open_eur":  None,
    "cooldowns":          {},
    "tick":               0,
    "daily_brief_sent":   None,
    "weekly_report_sent": None,
    "focus_confirmed":    False,
    "focus_date":         None,
    "pending_trade":      None,
    "last_update_id":     None,
    "consecutive_losses": 0,
    "daily_trades":       0,
    "daily_trade_date":   None,
}

journal = []

# ═══════════════════════════════════════════════════════════════
#  JOURNAL
# ═══════════════════════════════════════════════════════════════
def load_journal():
    global journal
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                journal = json.load(f)
        except:
            journal = []

def save_journal():
    with open(LOG_FILE, "w") as f:
        json.dump(journal, f, indent=2)

# ═══════════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════════
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       msg,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"  [Telegram] {e}")

def get_updates():
    try:
        url    = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"timeout": 1}
        if state["last_update_id"]:
            params["offset"] = state["last_update_id"]
        r = requests.get(url, params=params, timeout=5)
        return r.json().get("result", [])
    except:
        return []

# ═══════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════
def fetch_quote(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        r   = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except:
        return None

def fetch_candles(symbol, interval="1h", range_="5d"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_}"
        r   = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        d   = r.json()["chart"]["result"][0]
        H   = d["indicators"]["quote"][0]["high"]
        L   = d["indicators"]["quote"][0]["low"]
        O   = d["indicators"]["quote"][0]["open"]
        C   = d["indicators"]["quote"][0]["close"]
        T   = d["timestamps"]
        return [{"t": T[i], "o": O[i], "h": H[i], "l": L[i], "c": C[i]}
                for i in range(len(C)) if C[i] and H[i] and L[i]]
    except:
        return []

# ═══════════════════════════════════════════════════════════════
#  TIME + SESSION
# ═══════════════════════════════════════════════════════════════
def now_eat():
    return datetime.now(EAT)

def session_info():
    t    = now_eat()
    mins = t.hour * 60 + t.minute

    # London: 09:00–11:30 EAT
    # NY:     15:30–17:30 EAT
    in_london    = 540  <= mins <= 690
    in_ny        = 930  <= mins <= 1050
    kill_london  = 540  <= mins <= 570   # 09:00–09:30 manipulation
    kill_ny      = 930  <= mins <= 960   # 15:30–16:00 manipulation
    prime_london = 600  <= mins <= 690   # 10:00–11:30 expansion
    prime_ny     = 990  <= mins <= 1050  # 16:30–17:30 expansion

    active = in_london or in_ny
    kill   = kill_london or kill_ny
    prime  = prime_london or prime_ny

    name   = "🇬🇧 London" if in_london else "🇺🇸 New York" if in_ny else ""
    window = ("🔪 Kill Zone" if kill else
              "🔥 Prime"     if prime else
              "✓ Good"       if active else
              "💤 Closed")

    return {
        "active":    active,
        "kill":      kill,
        "prime":     prime,
        "london":    in_london,
        "ny":        in_ny,
        "name":      name,
        "window":    window,
        "mins":      mins,
        "hour":      t.hour,
        "minute":    t.minute,
        "weekday":   t.weekday(),
        "date_str":  t.strftime("%m-%d"),
        "today_str": t.strftime("%Y-%m-%d"),
        "time_str":  t.strftime("%H:%M EAT"),
        "time_obj":  t,
    }

def is_quiet():
    h = now_eat().hour
    return h >= QUIET_START or h < QUIET_END

def news_today():
    return NEWS_EVENTS.get(now_eat().strftime("%m-%d"))

# ═══════════════════════════════════════════════════════════════
#  ASIAN RANGE
# ═══════════════════════════════════════════════════════════════
def asian_range(candles):
    asian = [c for c in candles
             if c.get("t") and 0 <= datetime.fromtimestamp(c["t"], tz=EAT).hour < 6]
    if not asian:
        return None, None
    return max(c["h"] for c in asian), min(c["l"] for c in asian)

# ═══════════════════════════════════════════════════════════════
#  MARKET REGIME
# ═══════════════════════════════════════════════════════════════
def market_regime(candles):
    if len(candles) < 15:
        return "unknown"
    r   = candles[-20:]
    hh  = sum(1 for i in range(1, len(r)) if r[i]["h"] > r[i-1]["h"])
    ll  = sum(1 for i in range(1, len(r)) if r[i]["l"] < r[i-1]["l"])
    hl  = sum(1 for i in range(1, len(r)) if r[i]["l"] > r[i-1]["l"])
    lh  = sum(1 for i in range(1, len(r)) if r[i]["h"] < r[i-1]["h"])
    avg = sum(c["h"] - c["l"] for c in r) / len(r)
    if avg < 0.8:
        return "choppy"
    if hh > ll + 4 and hl > lh:
        return "trending_bull"
    if ll > hh + 4 and lh > hl:
        return "trending_bear"
    if abs(hh - ll) <= 2:
        return "ranging"
    return "choppy"

# ═══════════════════════════════════════════════════════════════
#  HTF BIAS
# ═══════════════════════════════════════════════════════════════
def htf_bias(h4, h1):
    def trend(c, n=15):
        if len(c) < n: return "neutral"
        r  = c[-n:]
        hh = sum(1 for i in range(1, len(r)) if r[i]["h"] > r[i-1]["h"])
        ll = sum(1 for i in range(1, len(r)) if r[i]["l"] < r[i-1]["l"])
        if hh > ll + 3: return "bull"
        if ll > hh + 3: return "bear"
        return "neutral"
    h4t = trend(h4, 15)
    h1t = trend(h1, 20)
    if h4t == h1t and h4t != "neutral": return h4t
    if h4t != "neutral": return h4t
    return "neutral"

# ═══════════════════════════════════════════════════════════════
#  KEY LEVELS
# ═══════════════════════════════════════════════════════════════
def detect_levels(candles, price, a_high=None, a_low=None):
    if not candles or not price:
        return []
    levels = []

    for i in range(2, len(candles) - 2):
        c = candles[i]
        if all(c["h"] >= candles[i+j]["h"] for j in [-2,-1,1,2]):
            levels.append({"price": c["h"], "type": "R",   "label": "Swing High", "touches": 1})
        if all(c["l"] <= candles[i+j]["l"] for j in [-2,-1,1,2]):
            levels.append({"price": c["l"], "type": "S",   "label": "Swing Low",  "touches": 1})

    recent = candles[-48:]
    if recent:
        levels.append({"price": max(c["h"] for c in recent), "type": "PDH", "label": "Prev Day High", "touches": 2})
        levels.append({"price": min(c["l"] for c in recent), "type": "PDL", "label": "Prev Day Low",  "touches": 2})

    if a_high: levels.append({"price": a_high, "type": "AR", "label": "Asian High", "touches": 2})
    if a_low:  levels.append({"price": a_low,  "type": "AR", "label": "Asian Low",  "touches": 2})

    base = round(price / 25) * 25
    for rn in range(int(base) - 75, int(base) + 100, 25):
        levels.append({"price": float(rn), "type": "RN", "label": f"Round ${rn}", "touches": 1})

    clustered = []
    for lv in sorted(levels, key=lambda x: x["price"]):
        ex = next((c for c in clustered if abs(c["price"] - lv["price"]) < 0.8), None)
        if ex:
            ex["touches"] += 1
        else:
            clustered.append(dict(lv))

    return sorted(clustered, key=lambda x: abs(x["price"] - price))[:10]

# ═══════════════════════════════════════════════════════════════
#  PREMIUM / DISCOUNT
# ═══════════════════════════════════════════════════════════════
def premium_discount(candles, price):
    if len(candles) < 20:
        return None, "Unknown"
    r   = candles[-20:]
    sh  = max(c["h"] for c in r)
    sl  = min(c["l"] for c in r)
    rng = sh - sl
    if rng == 0:
        return None, "Flat"
    eq  = sl + rng * 0.5
    pct = (price - sl) / rng * 100
    if price < eq:
        return "discount", f"Discount {pct:.0f}%"
    return "premium", f"Premium {pct:.0f}%"

# ═══════════════════════════════════════════════════════════════
#  LIQUIDITY SWEEP
# ═══════════════════════════════════════════════════════════════
def check_sweep(candles, levels):
    if len(candles) < 3:
        return False, None, None
    recent = candles[-5:]
    for lv in levels[:6]:
        for c in recent:
            if lv["type"] in ["R","PDH","AR","RN"]:
                if c["h"] > lv["price"] and c["c"] < lv["price"]:
                    return True, "SELL", f"Swept above {lv['label']} @ {lv['price']:.2f}"
            if lv["type"] in ["S","PDL","AR","RN"]:
                if c["l"] < lv["price"] and c["c"] > lv["price"]:
                    return True, "BUY",  f"Swept below {lv['label']} @ {lv['price']:.2f}"
    return False, None, None

# ═══════════════════════════════════════════════════════════════
#  CANDLESTICK PATTERNS (pure price action)
# ═══════════════════════════════════════════════════════════════
def detect_patterns(candles, levels, price):
    if len(candles) < 5:
        return [], None
    patterns = []
    c0, c1, c2, c3 = candles[-1], candles[-2], candles[-3], candles[-4]
    near  = next((lv for lv in levels if abs(lv["price"] - price) < PROXIMITY), None)
    total = c0["h"] - c0["l"]
    if total == 0:
        return [], None

    body  = abs(c0["c"] - c0["o"])
    upper = c0["h"] - max(c0["c"], c0["o"])
    lower = min(c0["c"], c0["o"]) - c0["l"]
    bias  = None

    # PIN BAR
    if near and body > 0:
        if upper / total > 0.55 and upper > body * 2 and near["type"] in ["R","PDH","AR","RN"]:
            patterns.append("🕯 Bearish Pin Bar")
            bias = "SELL"
        if lower / total > 0.55 and lower > body * 2 and near["type"] in ["S","PDL","AR","RN"]:
            patterns.append("🕯 Bullish Pin Bar")
            bias = "BUY"

    # ENGULFING
    prev_body = abs(c1["c"] - c1["o"])
    if near and prev_body > 0 and body > prev_body * 1.4:
        if c0["c"] < c0["o"] and c0["o"] >= max(c1["c"],c1["o"]) and c0["c"] <= min(c1["c"],c1["o"]):
            patterns.append("⬛ Bearish Engulfing")
            bias = "SELL"
        if c0["c"] > c0["o"] and c0["o"] <= min(c1["c"],c1["o"]) and c0["c"] >= max(c1["c"],c1["o"]):
            patterns.append("⬜ Bullish Engulfing")
            bias = "BUY"

    # REJECTION / FAKEOUT
    for lv in levels[:5]:
        if c1["h"] > lv["price"] and c1["c"] < lv["price"] and abs(lv["price"] - price) < 6:
            patterns.append(f"🪤 Bearish Fakeout above {lv['price']:.2f}")
            bias = "SELL"
        if c1["l"] < lv["price"] and c1["c"] > lv["price"] and abs(lv["price"] - price) < 6:
            patterns.append(f"🪤 Bullish Fakeout below {lv['price']:.2f}")
            bias = "BUY"

    # DOUBLE TOP
    for lv in [l for l in levels if l["type"] in ["R","PDH"]]:
        if (abs(c3["h"] - lv["price"]) < 2.5 and abs(c0["h"] - lv["price"]) < 2.5
                and abs(c3["h"] - c0["h"]) < 1.5):
            patterns.append(f"🔴 Double Top @ {lv['price']:.2f}")
            bias = "SELL"

    # DOUBLE BOTTOM
    for lv in [l for l in levels if l["type"] in ["S","PDL"]]:
        if (abs(c3["l"] - lv["price"]) < 2.5 and abs(c0["l"] - lv["price"]) < 2.5
                and abs(c3["l"] - c0["l"]) < 1.5):
            patterns.append(f"🟢 Double Bottom @ {lv['price']:.2f}")
            bias = "BUY"

    # INSIDE BAR
    if c0["h"] < c1["h"] and c0["l"] > c1["l"]:
        patterns.append("📦 Inside Bar — compression")

    return patterns, bias

# ═══════════════════════════════════════════════════════════════
#  DISPLACEMENT QUALITY
# ═══════════════════════════════════════════════════════════════
def check_displacement(candles):
    if len(candles) < 5:
        return False, "Not enough data"
    c0    = candles[-1]
    prev3 = candles[-4:-1]
    total = c0["h"] - c0["l"]
    if total == 0:
        return False, "Flat candle"
    body  = abs(c0["c"] - c0["o"])
    if body / total < 0.60:
        return False, f"Weak body {body/total*100:.0f}%"
    bull_break = c0["c"] > max(c["h"] for c in prev3)
    bear_break = c0["c"] < min(c["l"] for c in prev3)
    if not bull_break and not bear_break:
        return False, "No structural break"
    direction = "Bullish" if bull_break else "Bearish"
    return True, f"Strong {direction} move ({body/total*100:.0f}% body)"

# ═══════════════════════════════════════════════════════════════
#  FAIR VALUE GAP
# ═══════════════════════════════════════════════════════════════
def find_fvg(candles, price, lookback=15):
    fvgs   = []
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    for i in range(1, len(recent) - 1):
        p, n = recent[i-1], recent[i+1]
        if p["l"] > n["h"] and abs(((p["l"]+n["h"])/2) - price) < 10:
            fvgs.append({"type": "bull", "top": p["l"], "bot": n["h"], "mid": (p["l"]+n["h"])/2})
        if p["h"] < n["l"] and abs(((p["h"]+n["l"])/2) - price) < 10:
            fvgs.append({"type": "bear", "top": n["l"], "bot": p["h"], "mid": (p["h"]+n["l"])/2})
    return fvgs

# ═══════════════════════════════════════════════════════════════
#  STRUCTURE BREAK
# ═══════════════════════════════════════════════════════════════
def check_structure(candles):
    if len(candles) < 12:
        return None
    prev      = candles[-12:-3]
    curr      = candles[-1]
    last_high = max(c["h"] for c in prev)
    last_low  = min(c["l"] for c in prev)
    if curr["c"] > last_high: return "Break of Structure ↑ Bullish"
    if curr["c"] < last_low:  return "Break of Structure ↓ Bearish"
    return None

# ═══════════════════════════════════════════════════════════════
#  H4 POSITION
# ═══════════════════════════════════════════════════════════════
def h4_position(h4, price):
    if not h4: return False, "No H4 data"
    c   = h4[-1]
    rng = c["h"] - c["l"]
    if rng == 0: return False, "Flat H4"
    pct = (price - c["l"]) / rng
    if pct >= 0.72: return True,  f"Top of H4 candle ({pct*100:.0f}%)"
    if pct <= 0.28: return True,  f"Bottom of H4 candle ({pct*100:.0f}%)"
    return False, f"Middle of H4 ({pct*100:.0f}%) — weak position"

# ═══════════════════════════════════════════════════════════════
#  DXY
# ═══════════════════════════════════════════════════════════════
def dxy_check(dxy_candles, price, prev):
    if not dxy_candles or len(dxy_candles) < 3 or not prev:
        return False, "No DXY data"
    dxy_up    = dxy_candles[-1]["c"] > dxy_candles[-3]["c"]
    asset_up  = price > prev
    confirmed = asset_up != dxy_up
    label     = ("DXY ↑ · Gold ↓ ✅" if dxy_up and not asset_up else
                 "DXY ↓ · Gold ↑ ✅" if not dxy_up and asset_up else
                 "DXY not inverse ❌")
    return confirmed, label

# ═══════════════════════════════════════════════════════════════
#  STACKED ZONE
# ═══════════════════════════════════════════════════════════════
def stacked_zone(levels, fvgs, price):
    near    = [lv for lv in levels if abs(lv["price"] - price) < 5]
    has_fvg = any(abs(f["mid"] - price) < 5 for f in fvgs)
    has_rn  = any(lv["type"] == "RN"               for lv in near)
    has_sr  = any(lv["type"] in ["R","S","PDH","PDL"] for lv in near)
    has_ar  = any(lv["type"] == "AR"               for lv in near)
    count   = sum([has_fvg, has_rn, has_sr, has_ar])
    if count >= 3: return True,  f"🔥 Stacked zone — {count} confluences"
    if count == 2: return False, f"Double confluence — {count} levels"
    return False, "Single level"

# ═══════════════════════════════════════════════════════════════
#  TRADE MANAGEMENT CALCULATOR
# ═══════════════════════════════════════════════════════════════
def calc_trade(direction, price, candles, pair="GOLD"):
    if not candles:
        return None
    c0  = candles[-1]
    buf = 1.5 if pair == "GOLD" else 0.00050

    if direction == "BUY":
        entry  = round(price, 5)
        sl     = round(c0["l"] - buf, 5)
        risk   = entry - sl
        if risk <= 0: return None
        be     = round(entry + risk, 5)        # 1:1 — move SL to BE here
        tp1    = round(entry + risk * 2, 5)    # 1:2 — close majority
        tp2    = round(entry + risk * 3, 5)    # 1:3 — close rest
        tp3    = round(entry + risk * 5, 5)    # 1:5 — runner (A+ only)
    else:
        entry  = round(price, 5)
        sl     = round(c0["h"] + buf, 5)
        risk   = sl - entry
        if risk <= 0: return None
        be     = round(entry - risk, 5)
        tp1    = round(entry - risk * 2, 5)
        tp2    = round(entry - risk * 3, 5)
        tp3    = round(entry - risk * 5, 5)

    rr_valid = risk > 0 and abs(tp2 - entry) / risk >= 3

    return {
        "direction": direction,
        "entry":    entry,
        "sl":       sl,
        "be":       be,
        "tp1":      tp1,
        "tp2":      tp2,
        "tp3":      tp3,
        "risk":     round(risk, 3),
        "rr_valid": rr_valid,
    }

# ═══════════════════════════════════════════════════════════════
#  SCORING ENGINE
# ═══════════════════════════════════════════════════════════════
def score_setup(s):
    score = 0
    bd    = []
    rules = [
        ("htf",          2, "HTF bias"),
        ("sweep",        2, "Liquidity sweep"),
        ("structure",    2, "Structure break"),
        ("displacement", 2, "Strong displacement"),
        ("session",      1, "Session active"),
        ("kill_zone",    1, "Kill zone"),
        ("fvg",          1, "FVG present"),
        ("pd_zone",      1, "P/D zone aligned"),
        ("stacked",      1, "Stacked zone"),
        ("rr_valid",     2, "R:R ≥ 1:3"),
    ]
    penalties = [
        ("news",             -2, "News risk"),
        ("choppy",           -2, "Choppy market"),
        ("weak_disp",        -2, "Weak displacement"),
        ("h4_middle",        -1, "Middle of H4"),
    ]
    for key, pts, label in rules:
        if s.get(key):
            score += pts
            bd.append(f"{label} +{pts}")
    for key, pts, label in penalties:
        if s.get(key):
            score += pts
            bd.append(f"{label} {pts}")

    grade = ("💎 A+" if score >= 12 else
             "✅ A"  if score >= 9  else
             "⚠️ B"  if score >= 6  else
             "❌ No Trade")
    return score, grade, bd

# ═══════════════════════════════════════════════════════════════
#  ALERT MESSAGE — HUMAN VOICE
# ═══════════════════════════════════════════════════════════════
def build_message(pair, price, score, grade, direction, trade,
                  patterns, sweep_detail, structure_detail,
                  disp_detail, dxy_detail, stacked_detail,
                  pd_detail, h4_detail, fvgs, sess,
                  regime, breakdown, near_level):

    fmt        = ".2f" if pair == "GOLD" else ".5f"
    pair_label = "Gold" if pair == "GOLD" else "EURUSD"
    dir_emoji  = "🟢 BUY" if direction == "BUY" else "🔴 SELL"

    # Opening — human mentor voice
    if grade == "💎 A+":
        opening = (f"Rami, this is the one. A+ setup on {pair_label}.\n"
                   f"Everything lines up. Execute the plan. No second guessing.")
    elif grade == "✅ A":
        opening = (f"Solid setup forming on {pair_label}, Rami.\n"
                   f"Good conditions. Standard size. Follow your rules.")
    elif grade == "⚠️ B":
        opening = (f"There's something on {pair_label} but it's not clean.\n"
                   f"B grade — I'd leave this one. Wait for better.")
    else:
        opening = f"Nothing worth trading on {pair_label}. Stand down."

    # Regime line
    regime_map = {
        "trending_bull": "📈 Trending Bullish — buy setups only",
        "trending_bear": "📉 Trending Bearish — sell setups only",
        "ranging":       "↔ Ranging — wait for sweep of the range",
        "choppy":        "⚠️ Choppy — no trade environment",
    }

    # Patterns
    pat_str = "\n".join([f"  • {p}" for p in patterns[:3]]) if patterns else "  • None detected"

    # FVG line
    fvg_str = f"  FVG @ {fvgs[0]['mid']:{fmt}} ({fvgs[0]['type'].upper()})" if fvgs else "  No FVG nearby"

    # Trade management block
    trade_block = ""
    if trade:
        rr_plan = ("Close 100% at TP1" if score < 9 else
                   "Close 80% at TP1 · move SL to BE · let 20% run to TP2" if score < 12 else
                   "Close 80% at TP1 · move SL to BE · let 20% run to TP3")

        trade_block = f"""
━━━━━━━━━━━━━━━━━━━━━━
📐 <b>TRADE MANAGEMENT</b>
━━━━━━━━━━━━━━━━━━━━━━
Direction : <b>{dir_emoji}</b>
Entry     : <b>{trade['entry']:{fmt}}</b>
Stop Loss : <b>{trade['sl']:{fmt}}</b>  (risk: {trade['risk']:{fmt}} pts)

⚡ When 1:1 hit ({trade['be']:{fmt}}) → Move SL to Breakeven

TP1 (1:2) : <b>{trade['tp1']:{fmt}}</b>  ← close majority here
TP2 (1:3) : <b>{trade['tp2']:{fmt}}</b>  ← close rest
TP3 (1:5) : <b>{trade['tp3']:{fmt}}</b>  ← runner (A+ only)

Plan: {rr_plan}
━━━━━━━━━━━━━━━━━━━━━━"""

    # Score breakdown
    bd_str = " · ".join(breakdown)

    msg = f"""⚡ <b>{grade} — {pair_label}</b>

{opening}

📊 <b>CONTEXT</b>
{regime_map.get(regime, regime)}
{sess['name']} {sess['window']} · {sess['time_str']}
HTF: {'📈 Bullish' if 'bull' in regime else '📉 Bearish' if 'bear' in regime else '↔ Neutral'}

💧 <b>PRICE ACTION</b>
Sweep     : {sweep_detail or '—'}
Structure : {structure_detail or 'Pending'}
Momentum  : {disp_detail}

🎯 <b>ZONE</b>
{stacked_detail}
{fvg_str}
P/D       : {pd_detail}
H4 Pos    : {h4_detail}
DXY       : {dxy_detail}
Level     : {near_level['label']} @ {near_level['price']:{fmt}} ({near_level['touches']}x touched)

🕯 <b>PATTERNS</b>
{pat_str}
{trade_block}
📋 Score: {score}/14 → {grade}
{bd_str}

💬 Reply <b>took it</b> to log · /status · /levels · /help"""

    return msg

# ═══════════════════════════════════════════════════════════════
#  DAILY BRIEF
# ═══════════════════════════════════════════════════════════════
def send_daily_brief():
    g   = state["gold_price"]
    e   = state["eur_price"]
    d   = state["dxy_price"]
    tg  = htf_bias(state["gold_h4"], state["gold_h1"])
    te  = htf_bias(state["eur_h4"],  state["eur_h1"])
    ahg = state["asian_high_gold"]
    alg = state["asian_low_gold"]
    ahe = state["asian_high_eur"]
    ale = state["asian_low_eur"]
    lvg = detect_levels(state["gold_h1"], g or 0, ahg, alg)
    lve = detect_levels(state["eur_h1"],  e or 0, ahe, ale)
    tpg = "\n".join([f"  {l['type']} {l['price']:.2f} — {l['label']}" for l in lvg[:4]]) or "  Loading..."
    tpe = "\n".join([f"  {l['type']} {l['price']:.5f} — {l['label']}" for l in lve[:4]]) or "  Loading..."
    news  = news_today()
    wins  = sum(1 for t in journal if t.get("result") == "win")
    total = len([t for t in journal if t.get("result") in ["win","loss"]])
    wr    = f"{wins}/{total} ({int(wins/total*100)}%)" if total else "No trades yet"
    t     = now_eat()

    send(f"""🌅 <b>Good morning Rami.</b>
{t.strftime('%A, %d %B %Y')}

New day. Fresh start. Stick to the system today.

📊 <b>MARKET</b>
Gold   : {g:.2f if g else '—'} · {'📈' if tg=='bull' else '📉' if tg=='bear' else '↔'} {tg}
EURUSD : {e:.5f if e else '—'} · {'📈' if te=='bull' else '📉' if te=='bear' else '↔'} {te}
DXY    : {d:.3f if d else '—'}

🌙 <b>ASIAN RANGE (watch for sweeps)</b>
Gold   : {alg:.2f if alg else '—'} — {ahg:.2f if ahg else '—'}
EURUSD : {ale:.5f if ale else '—'} — {ahe:.5f if ahe else '—'}

📐 <b>GOLD KEY LEVELS</b>
{tpg}

📐 <b>EURUSD KEY LEVELS</b>
{tpe}

⏰ <b>SESSIONS TODAY</b>
🔪 London Kill Zone  : 09:00–09:30 EAT
🔥 London Prime      : 10:00–11:30 EAT
🔪 NY Kill Zone      : 15:30–16:00 EAT
🔥 NY Prime          : 16:30–17:30 EAT

{'⚠️ NEWS TODAY: ' + news if news else '✅ No major news today'}

📋 <b>YOUR STATS</b>
Win Rate  : {wr}
Max trades: 2 per day

Reply <b>YES</b> when you're ready to trade 💪""")
    print("  [Brief] Sent")

# ═══════════════════════════════════════════════════════════════
#  WEEKLY REPORT
# ═══════════════════════════════════════════════════════════════
def send_weekly_report():
    week = now_eat().isocalendar()[1]
    wt   = [t for t in journal if t.get("week") == week]
    wins = sum(1 for t in wt if t.get("result") == "win")
    loss = sum(1 for t in wt if t.get("result") == "loss")
    tot  = wins + loss
    wr   = int(wins/tot*100) if tot else 0

    perf = ("🔥 Great week Rami. The discipline is showing." if wins > loss
            else "📚 Tough week. Review every setup. What rule did you miss each time? Come back Monday sharp.")

    send(f"""📊 <b>WEEKLY REPORT</b>
{now_eat().strftime('%d %B %Y')}

Trades : {tot}
Wins   : {wins} · Losses: {loss}
Win Rate: {wr}%

{perf}

Rest this weekend. Review your journal. The market will be there Monday. 💪""")
    print("  [Report] Sent")

# ═══════════════════════════════════════════════════════════════
#  COMMANDS
# ═══════════════════════════════════════════════════════════════
def handle_commands():
    updates = get_updates()
    for upd in updates:
        state["last_update_id"] = upd["update_id"] + 1
        msg  = upd.get("message", {})
        text = msg.get("text", "").strip().lower()
        cid  = str(msg.get("chat", {}).get("id", ""))
        if cid != CHAT_ID:
            continue

        sess  = session_info()
        today = sess["today_str"]

        if text == "yes":
            state["focus_confirmed"] = True
            state["focus_date"]      = today
            send("✅ Focus confirmed. Alerts are active. Trade with discipline today Rami. Max 2 trades. 💪")

        elif text == "no":
            send("Understood. Observation mode today. Watch, learn, take notes. That's also valuable.")

        elif "took it" in text and state["pending_trade"]:
            pt = state["pending_trade"]
            journal.append({
                "date":      now_eat().strftime("%Y-%m-%d %H:%M"),
                "pair":      pt["pair"],
                "direction": pt["direction"],
                "entry":     pt["entry"],
                "sl":        pt["sl"],
                "tp1":       pt["tp1"],
                "result":    "open",
                "week":      now_eat().isocalendar()[1],
            })
            save_journal()
            state["pending_trade"]  = None
            state["daily_trades"]  += 1
            fmt = ".2f" if pt["pair"] == "GOLD" else ".5f"
            send(f"✅ <b>Trade logged.</b>\n{pt['pair']} {pt['direction']} @ {pt['entry']:{fmt}}\nSL: {pt['sl']:{fmt}} · TP1: {pt['tp1']:{fmt}}\n\nMove SL to BE when 1:1 hits. Update result: reply <b>win</b> or <b>loss</b>.")

        elif text == "win" and journal:
            journal[-1]["result"] = "win"
            state["consecutive_losses"] = 0
            save_journal()
            send("🏆 Win logged. That's the system working. Stay focused, don't get overconfident.")

        elif text == "loss" and journal:
            journal[-1]["result"] = "loss"
            state["consecutive_losses"] += 1
            save_journal()
            if state["consecutive_losses"] >= 2:
                send(f"📚 Loss logged. {state['consecutive_losses']} in a row Rami.\n\nStep back. Don't force the next one. Review what rule you missed. The money will come back when the setups are right.")
            else:
                send("📚 Loss logged. Review the setup — was it a rule violation or just bad luck? Move on. Don't revenge trade.")

        elif text == "/status":
            g    = state["gold_price"]
            e    = state["eur_price"]
            d    = state["dxy_price"]
            sess = session_info()
            send(f"""📡 <b>STATUS</b>
Gold   : {g:.2f if g else '—'}
EURUSD : {e:.5f if e else '—'}
DXY    : {d:.3f if d else '—'}
Regime : {market_regime(state['gold_h1'])}
Session: {sess['name'] if sess['active'] else 'Closed'} {sess['window']}
Time   : {sess['time_str']}
News   : {news_today() or 'None today'}
Focus  : {'✅ Active' if state['focus_confirmed'] and state['focus_date'] == today else '❌ Reply YES to activate'}
Trades : {state['daily_trades']}/2 today
Tick   : #{state['tick']}""")

        elif text == "/levels":
            g   = state["gold_price"]
            lvs = detect_levels(state["gold_h1"], g or 0,
                                state["asian_high_gold"], state["asian_low_gold"])
            lines = "\n".join([f"  {l['type']} {l['price']:.2f} — {l['label']}" for l in lvs[:6]])
            send(f"📐 <b>Gold Levels</b>\n{lines}\nAsian: {state['asian_low_gold']:.2f if state['asian_low_gold'] else '—'} — {state['asian_high_gold']:.2f if state['asian_high_gold'] else '—'}")

        elif text == "/journal":
            if not journal:
                send("📋 No trades yet. Reply <b>took it</b> after an alert to log.")
            else:
                recent = journal[-5:]
                lines  = "\n".join([f"  {t['date']} | {t.get('pair','?')} {t.get('direction','')} | {t.get('result','open').upper()}" for t in recent])
                wins   = sum(1 for t in journal if t.get("result") == "win")
                total  = len([t for t in journal if t.get("result") in ["win","loss"]])
                send(f"📋 <b>Last 5 trades:</b>\n{lines}\n\nTotal: {total} | Wins: {wins} | WR: {int(wins/total*100) if total else 0}%")

        elif text == "/help":
            send("""📖 <b>Commands</b>

<b>YES</b>      → activate alerts
<b>NO</b>       → observation mode
<b>took it</b>  → log trade
<b>win</b>      → mark win
<b>loss</b>     → mark loss

/status   → prices + session
/levels   → key levels
/journal  → trade history
/help     → this menu

XauZone99Bot v5.0 — built for Rami 💪""")

# ═══════════════════════════════════════════════════════════════
#  MAIN ANALYSIS
# ═══════════════════════════════════════════════════════════════
def analyze(pair, price, prev, h1, h4, a_high, a_low, sess):
    if not price or not h1 or len(h1) < 15:
        return

    # Max 2 trades per day
    if state["daily_trades"] >= 2:
        print(f"  [{pair}] Max 2 trades reached today")
        return

    # Market regime
    regime = market_regime(h1)
    if regime == "choppy":
        print(f"  [{pair}] Choppy — skip")
        return

    # Build full context
    levels              = detect_levels(h1, price, a_high, a_low)
    near                = next((lv for lv in levels if abs(lv["price"] - price) < PROXIMITY), None)
    bias                = htf_bias(h4, h1)
    swept, sw_dir, sw_d = check_sweep(h1, levels)
    patterns, pat_bias  = detect_patterns(h1, levels, price)
    disp_ok, disp_d     = check_displacement(h1)
    structure_d         = check_structure(h1)
    fvgs                = find_fvg(h1, price)
    stk, stk_d          = stacked_zone(levels, fvgs, price)
    h4_ok, h4_d         = h4_position(h4, price)
    dxy_ok, dxy_d       = dxy_check(state["dxy_h1"], price, prev)
    pd_zone, pd_d       = premium_discount(h1, price)
    news                = news_today()

    # Direction — from sweep, pattern, or bias
    direction = sw_dir or pat_bias or ("BUY" if bias == "bull" else "SELL" if bias == "bear" else None)
    if not direction:
        return

    # Premium/Discount alignment
    pd_ok = ((direction == "BUY"  and pd_zone == "discount") or
             (direction == "SELL" and pd_zone == "premium"))

    # Trend alignment
    trend_ok = bias == "neutral" or (bias == "bull" and direction == "BUY") or (bias == "bear" and direction == "SELL")

    # Build score
    s = {
        "htf":          trend_ok,
        "sweep":        swept,
        "structure":    structure_d is not None,
        "displacement": disp_ok,
        "session":      sess["active"],
        "kill_zone":    sess["kill"],
        "fvg":          len(fvgs) > 0,
        "pd_zone":      pd_ok,
        "stacked":      stk,
        "rr_valid":     True,
        "news":         news is not None,
        "choppy":       regime == "choppy",
        "weak_disp":    not disp_ok,
        "h4_middle":    not h4_ok,
    }

    score, grade, breakdown = score_setup(s)
    min_req = 9 if (sess["kill"] or sess["prime"]) else 11

    print(f"  [{pair}] {price:.2f} Score:{score}/14 {grade} Dir:{direction} Regime:{regime}")

    if score < min_req or not near:
        return

    # Execution gate — ALL must be true
    if not all([sess["active"], swept or len(patterns) > 0, score >= min_req]):
        return

    # Cooldown
    key    = f"{pair}_{round(price/5)*5}"
    now_ts = time.time()
    if key in state["cooldowns"] and now_ts - state["cooldowns"][key] < COOLDOWN:
        return
    state["cooldowns"][key] = now_ts

    # Trade calc
    trade = calc_trade(direction, price, h1, pair)
    if not trade:
        return

    # Update RR in score
    s["rr_valid"] = trade["rr_valid"]
    score, grade, breakdown = score_setup(s)

    # Skip B unless stacked
    if grade == "⚠️ B" and not stk:
        print(f"  [{pair}] B grade without stacked zone — skip")
        return

    # Save pending
    state["pending_trade"] = {
        "pair":      pair,
        "direction": direction,
        "entry":     trade["entry"],
        "sl":        trade["sl"],
        "tp1":       trade["tp1"],
    }

    msg = build_message(
        pair, price, score, grade, direction, trade,
        patterns, sw_d, structure_d, disp_d, dxy_d,
        stk_d, pd_d, h4_d, fvgs, sess, regime,
        breakdown, near
    )

    send(msg)
    print(f"  ✅ [{pair}] Alert sent {score}/14 {grade}")

# ═══════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════
def run():
    load_journal()
    print(f"""
╔══════════════════════════════════════════════╗
║    XauZone99Bot v{VERSION} — STARTING               ║
║    Pure Price Action · High Probability      ║
║    Gold + EURUSD · Built for Rami            ║
╚══════════════════════════════════════════════╝
""")
    send(f"""🟢 <b>XauZone99Bot v{VERSION} is LIVE</b>

Yo Rami. I'm watching Gold and EURUSD.

I only alert on A grade setups and above. No noise. No low quality trades.

Every morning at 9am you get your brief. Reply <b>YES</b> to activate alerts.

Sessions:
🇬🇧 London : 09:00–11:30 EAT
🇺🇸 New York: 15:30–17:30 EAT

Max 2 trades per day. Protect the accounts.

/help for commands. Let's get it. 💪""")

    while True:
        try:
            state["tick"] += 1
            sess  = session_info()
            t     = sess["time_obj"]
            today = sess["today_str"]

            print(f"\n[Tick {state['tick']}] {sess['time_str']} {sess['name']} {sess['window']}")

            handle_commands()

            if is_quiet():
                print("  [Quiet hours]")
                time.sleep(CHECK_EVERY)
                continue

            # Reset daily trades at midnight
            if t.hour == 0 and t.minute < 4 and state["daily_trade_date"] != today:
                state["daily_trades"]      = 0
                state["daily_trade_date"]  = today
                state["london_open_gold"]  = None
                state["ny_open_gold"]      = None
                state["focus_confirmed"]   = False

            # Focus check 8:45am
            if t.hour == 8 and 45 <= t.minute <= 49 and state["focus_date"] != today:
                send(f"🧠 <b>Morning check, Rami.</b>\n\nAre you focused and ready to trade today?\n\nReply <b>YES</b> to activate alerts · <b>NO</b> for observation mode")
                state["focus_date"] = today

            # Daily brief 9am
            if t.hour == 9 and t.minute < 4 and state["daily_brief_sent"] != today:
                send_daily_brief()
                state["daily_brief_sent"] = today

            # Weekly report Sunday 8am
            wk = f"{t.isocalendar()[1]}-{t.year}"
            if sess["weekday"] == 6 and t.hour == 8 and t.minute < 4 and state["weekly_report_sent"] != wk:
                send_weekly_report()
                state["weekly_report_sent"] = wk

            # Fetch prices
            g = fetch_quote("GC=F")
            e = fetch_quote("EURUSD=X")
            d = fetch_quote("DX-Y.NYB")
            if g: state["gold_prev"], state["gold_price"] = state["gold_price"], g
            if e: state["eur_prev"],  state["eur_price"]  = state["eur_price"],  e
            if d: state["dxy_prev"],  state["dxy_price"]  = state["dxy_price"],  d
            print(f"  Gold:{state['gold_price']} EUR:{state['eur_price']} DXY:{state['dxy_price']}")

            # Candles every 5 ticks
            if state["tick"] % 5 == 1 or not state["gold_h1"]:
                gh1 = fetch_candles("GC=F",     "1h", "5d")
                gh4 = fetch_candles("GC=F",     "4h", "30d")
                eh1 = fetch_candles("EURUSD=X", "1h", "5d")
                eh4 = fetch_candles("EURUSD=X", "4h", "30d")
                dh1 = fetch_candles("DX-Y.NYB", "1h", "5d")
                if gh1: state["gold_h1"] = gh1
                if gh4: state["gold_h4"] = gh4
                if eh1: state["eur_h1"]  = eh1
                if eh4: state["eur_h4"]  = eh4
                if dh1: state["dxy_h1"]  = dh1
                print(f"  GH1:{len(state['gold_h1'])} GH4:{len(state['gold_h4'])} EH1:{len(state['eur_h1'])}")

            # Asian range
            ahg, alg = asian_range(state["gold_h1"])
            ahe, ale = asian_range(state["eur_h1"])
            state["asian_high_gold"], state["asian_low_gold"] = ahg, alg
            state["asian_high_eur"],  state["asian_low_eur"]  = ahe, ale

            # Session opens
            if sess["london"] and not state["london_open_gold"] and t.hour == 9 and t.minute < 4:
                state["london_open_gold"] = state["gold_price"]
            if sess["ny"] and not state["ny_open_gold"] and t.hour == 15 and t.minute < 34:
                state["ny_open_gold"] = state["gold_price"]

            # News warning
            news = news_today()
            if news and sess["active"] and t.minute in [0, 30]:
                send(f"⚠️ Rami — <b>{news}</b> is today. No trading 30 min around the release. Protect the account.")

            # Analyze — only if session active + focus confirmed
            if sess["active"]:
                if not state["focus_confirmed"] or state["focus_date"] != today:
                    print("  [Focus not confirmed]")
                else:
                    if state["gold_price"]:
                        analyze("GOLD",   state["gold_price"], state["gold_prev"],
                                state["gold_h1"], state["gold_h4"], ahg, alg, sess)
                    if state["eur_price"]:
                        analyze("EURUSD", state["eur_price"],  state["eur_prev"],
                                state["eur_h1"],  state["eur_h4"],  ahe, ale, sess)

        except Exception as e:
            print(f"  [Error] {e}")

        time.sleep(CHECK_EVERY)

# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    run()
