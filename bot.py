import os
import time
import random
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from tradingview_ta import TA_Handler, Interval
import sqlite3

app = Flask(__name__, template_folder='templates')

def init_db():
    conn = sqlite3.connect('trading_stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            user_id TEXT PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            last_update TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

TIMEFRAME_MAP = {
    '5 хв': Interval.INTERVAL_5_MINUTES,
    '10 хв': Interval.INTERVAL_5_MINUTES, 
    '15 хв': Interval.INTERVAL_15_MINUTES,
    '30 хв': Interval.INTERVAL_30_MINUTES,
    '1 год': Interval.INTERVAL_1_HOUR,
}

_cache = {}
CACHE_TTL = 60

def get_exchange_and_screener(symbol):
    symbol = symbol.upper()
    if symbol in ['XAUUSD', 'XAGUSD']:
        return 'cfd', 'OANDA'
    return 'forex', 'FX_IDC'

def check_news_alert():
    now = datetime.now()
    h, m = now.hour, now.minute
    if (h == 14 and m >= 30) or (h in [15, 16]) or (h == 17 and m <= 30):
        return "⚠️ Увага: Час можливого виходу новин (висока волатильність)."
    return "✅ Новинний фон: Спокійно."

def get_safe_analysis(symbol, screener, exchange, interval, retries=3):
    key = f"{symbol}_{screener}_{exchange}_{interval}"
    now = time.time()
    if key in _cache:
        data, timestamp = _cache[key]
        if now - timestamp < CACHE_TTL:
            return data

    for attempt in range(retries):
        try:
            handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
            analysis = handler.get_analysis()
            if analysis and analysis.indicators:
                _cache[key] = (analysis, now)
                return analysis
        except Exception as e:
            if attempt == retries - 1:
                return None
            time.sleep((attempt + 1) * 1.5 + random.uniform(0.5, 1.0))
    return None

def calculate_signal(analysis, higher_15=None):
    ind = analysis.indicators
    rec = analysis.summary.get("RECOMMENDATION", "NEUTRAL")

    rsi = round(ind.get("RSI", 50), 2)
    stoch_k = round(ind.get("Stoch.K", 50), 2)
    macd = ind.get("MACD.macd", 0)
    macd_signal = ind.get("MACD.signal", 0)
    adx = round(ind.get("ADX", 20), 2)
    close = ind.get("close", 0)
    bb_upper = ind.get("BB.upper", close)
    bb_lower = ind.get("BB.lower", close)

    is_bull_macd = macd > macd_signal
    is_bear_macd = macd < macd_signal
    strong_trend = adx >= 18

    near_support = (rsi < 40 and stoch_k < 30) or (close <= bb_lower * 1.002)
    near_resistance = (rsi > 60 and stoch_k > 70) or (close >= bb_upper * 0.998)

    higher_rec = "NEUTRAL"
    if higher_15 and hasattr(higher_15, 'summary'):
        higher_rec = higher_15.summary.get("RECOMMENDATION", "NEUTRAL")

    higher_bear = "SELL" in higher_rec or "STRONG_SELL" in higher_rec
    higher_bull = "BUY" in higher_rec or "STRONG_BUY" in higher_rec

    signal = None
    quality = "Середня"
    reason = []

    if near_support and is_bull_macd and not higher_bear:
        signal = "CALL"
        quality = "Висока" if strong_trend else "Середня"
        reason.append("Відскік від підтримки")
    elif ("BUY" in rec or "STRONG_BUY" in rec) and is_bull_macd and not higher_bear and rsi < 68:
        signal = "CALL"
        quality = "Висока" if adx >= 24 else "Середня"
        reason.append("Тренд вгору")
    elif near_resistance and is_bear_macd and not higher_bull:
        signal = "PUT"
        quality = "Висока" if strong_trend else "Середня"
        reason.append("Відскік від опору")
    elif ("SELL" in rec or "STRONG_SELL" in rec) and is_bear_macd and not higher_bull and rsi > 32:
        signal = "PUT"
        quality = "Висока" if adx >= 24 else "Середня"
        reason.append("Тренд вниз")

    news_status = check_news_alert()

    if not signal:
        return "⚪️ ⚖️ РИНКОВИЙ ФЛЕТ — УТРИМАТИСЬ", "Низька", f"Флет / Немає сетапу | RSI: {rsi} | {news_status}"

    if signal == "CALL":
        emoji = "🔥" if quality == "Висока" else "🟢"
        text = f"{emoji} 📈 ВГОРУ (CALL)"
        if "підтримки" in reason[0].lower():
            text = f"{emoji} ЗОНА ПІДТРИМКИ: 📈 ВГОРУ (CALL)"
    else:
        emoji = "🔥" if quality == "Висока" else "🔴"
        text = f"{emoji} 📉 ВНИЗ (PUT)"
        if "опору" in reason[0].lower():
            text = f"{emoji} ЗОНА ОПОРУ: 📉 ВНИЗ (PUT)"

    details = (
        f"Ціна: {round(close, 5)} | RSI: {rsi} | Stoch: {stoch_k} | ADX: {adx} | "
        f"Якість: {quality} | {reason[0]} | {news_status}"
    )

    return text, quality, details

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/signal', methods=['POST'])
def get_signal():
    data = request.get_json() or {}
    symbol = data.get('symbol', 'EURUSD').upper()
    expiry = data.get('expiry', '5 хв')

    screener, exchange = get_exchange_and_screener(symbol)
    interval = TIMEFRAME_MAP.get(expiry, Interval.INTERVAL_5_MINUTES)

    try:
        analysis = get_safe_analysis(symbol, screener, exchange, interval)
        if not analysis:
            return jsonify({
                'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
                'price': "--",
                'details': "TradingView тимчасово обмежив доступ. Спробуйте через 5-10 сек.",
                'quality': "Помилка"
            })

        time.sleep(random.uniform(0.4, 0.8))
        higher_15 = None
        try:
            higher_15 = get_safe_analysis(symbol, screener, exchange, Interval.INTERVAL_15_MINUTES, retries=1)
        except:
            pass

        signal_text, quality, details = calculate_signal(analysis, higher_15)
        close_price = str(round(analysis.indicators.get("close", 0), 5))

        return jsonify({
            'signal': signal_text,
            'price': close_price,
            'details': details,
            'quality': quality
        })
    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
            'price': "--",
            'details': f"Збій: {str(e)[:35]}",
            'quality': "Помилка"
        })

@app.route('/api/stats/get', methods=['POST'])
def get_stats():
    data = request.get_json() or {}
    user_id = str(data.get('user_id', 'default_user'))
    conn = sqlite3.connect('trading_stats.db')
    cursor = conn.cursor()
    cursor.execute('SELECT wins, losses FROM stats WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    wins = row[0] if row else 0
    losses = row[1] if row else 0
    total = wins + losses
    winrate = round((wins / total * 100), 1) if total > 0 else 0.0

    return jsonify({'wins': wins, 'losses': losses, 'total': total, 'winrate': winrate})

@app.route('/api/stats/update', methods=['POST'])
def update_stats():
    data = request.get_json() or {}
    user_id = str(data.get('user_id', 'default_user'))
    result_type = data.get('type', 'win')

    conn = sqlite3.connect('trading_stats.db')
    cursor = conn.cursor()
    cursor.execute('SELECT wins, losses FROM stats WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()

    if row:
        wins, losses = row
        if result_type == 'win': wins += 1
        else: losses += 1
        cursor.execute('UPDATE stats SET wins = ?, losses = ?, last_update = ? WHERE user_id = ?',
                       (wins, losses, datetime.utcnow().isoformat(), user_id))
    else:
        wins = 1 if result_type == 'win' else 0
        losses = 0 if result_type == 'win' else 1
        cursor.execute('INSERT INTO stats (user_id, wins, losses, last_update) VALUES (?, ?, ?, ?)',
                       (user_id, wins, losses, datetime.utcnow().isoformat()))

    conn.commit()
    conn.close()
    
    total = wins + losses
    winrate = round((wins / total * 100), 1) if total > 0 else 0.0
    return jsonify({'wins': wins, 'losses': losses, 'total': total, 'winrate': winrate})

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    data = request.get_json() or {}
    user_id = str(data.get('user_id', 'default_user'))
    conn = sqlite3.connect('trading_stats.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE stats SET wins = 0, losses = 0, last_update = ? WHERE user_id = ?',
                   (datetime.utcnow().isoformat(), user_id))
    conn.commit()
    conn.close()
    return jsonify({'wins': 0, 'losses': 0, 'total': 0, 'winrate': 0.0})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
    
