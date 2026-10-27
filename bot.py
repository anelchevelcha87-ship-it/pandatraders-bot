import os
import time
import random
from flask import Flask, render_template, request, jsonify
from tradingview_ta import TA_Handler, Interval
import sqlite3
from datetime import datetime

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
    '15 хв': Interval.INTERVAL_15_MINUTES,
    '30 хв': Interval.INTERVAL_30_MINUTES,
    '1 год': Interval.INTERVAL_1_HOUR,
}

def get_exchange_and_screener(symbol):
    symbol = symbol.upper()
    if symbol in ['XAUUSD', 'XAGUSD']:
        return 'cfd', 'OANDA'
    if symbol.endswith('USDT') or symbol in ['BTCUSD', 'ETHUSD']:
        return 'crypto', 'BINANCE'
    return 'forex', 'FX_IDC'

def get_safe_analysis(symbol, screener, exchange, interval, retries=4):
    for attempt in range(retries):
        try:
            handler = TA_Handler(
                symbol=symbol,
                screener=screener,
                exchange=exchange,
                interval=interval
            )
            analysis = handler.get_analysis()
            if analysis and analysis.indicators:
                return analysis
        except Exception as e:
            if attempt == retries - 1:
                raise e
            sleep_time = (attempt + 1) * 1.8 + random.uniform(0.3, 1.2)
            time.sleep(sleep_time)
    return None

def calculate_signal_quality(analysis, higher_15, higher_1h):
    """Повертає: signal, quality, details"""
    ind = analysis.indicators
    rec = analysis.summary.get("RECOMMENDATION", "NEUTRAL")

    # Основні індикатори
    rsi = round(ind.get("RSI", 50), 2)
    stoch_k = round(ind.get("Stoch.K", 50), 2)
    stoch_d = round(ind.get("Stoch.D", 50), 2)
    macd = ind.get("MACD.macd", 0)
    macd_signal = ind.get("MACD.signal", 0)
    adx = round(ind.get("ADX", 20), 2)
    bb_upper = ind.get("BB.upper", 0)
    bb_lower = ind.get("BB.lower", 0)
    close = ind.get("close", 0)
    ema20 = ind.get("EMA20", close)
    ema50 = ind.get("EMA50", close)

    # Вищі ТФ
    rec_15 = higher_15.summary.get("RECOMMENDATION", "NEUTRAL") if higher_15 else "NEUTRAL"
    rec_1h = higher_1h.summary.get("RECOMMENDATION", "NEUTRAL") if higher_1h else "NEUTRAL"

    is_bull_macd = macd > macd_signal
    is_bear_macd = macd < macd_signal
    strong_trend = adx >= 22
    very_strong_trend = adx >= 28

    # Зони
    near_support = (rsi < 38 and stoch_k < 25) or (close <= bb_lower * 1.001)
    near_resistance = (rsi > 62 and stoch_k > 75) or (close >= bb_upper * 0.999)

    # Мульти-ТФ підтвердження
    bull_mtf = ("BUY" in rec_15 or "STRONG_BUY" in rec_15) and ("BUY" in rec_1h or "STRONG_BUY" in rec_1h or "NEUTRAL" in rec_1h)
    bear_mtf = ("SELL" in rec_15 or "STRONG_SELL" in rec_15) and ("SELL" in rec_1h or "STRONG_SELL" in rec_1h or "NEUTRAL" in rec_1h)

    # === ЛОГІКА СИГНАЛІВ (жорстка) ===
    signal = None
    quality = "Середня"
    reason = []

    # --- CALL ---
    if near_support and is_bull_macd and strong_trend and bull_mtf:
        signal = "CALL"
        quality = "Висока"
        reason.append("Відскік від підтримки + ADX + мульти-ТФ")
    elif ("BUY" in rec or "STRONG_BUY" in rec) and is_bull_macd and strong_trend and bull_mtf and rsi < 65:
        signal = "CALL"
        quality = "Висока" if very_strong_trend else "Середня"
        reason.append("Тренд вгору + підтвердження вищих ТФ")
    elif near_support and is_bull_macd and rsi < 42:
        signal = "CALL"
        quality = "Середня"
        reason.append("Відскік від зони підтримки")

    # --- PUT ---
    elif near_resistance and is_bear_macd and strong_trend and bear_mtf:
        signal = "PUT"
        quality = "Висока"
        reason.append("Відскік від опору + ADX + мульти-ТФ")
    elif ("SELL" in rec or "STRONG_SELL" in rec) and is_bear_macd and strong_trend and bear_mtf and rsi > 35:
        signal = "PUT"
        quality = "Висока" if very_strong_trend else "Середня"
        reason.append("Тренд вниз + підтвердження вищих ТФ")
    elif near_resistance and is_bear_macd and rsi > 58:
        signal = "PUT"
        quality = "Середня"
        reason.append("Відскік від зони опору")

    # Якщо немає чіткого сигналу — пропускаємо
    if not signal:
        return "SKIP", "Низька", "Немає чіткого сетапу. Краще утриматись."

    # Формуємо текст
    if signal == "CALL":
        emoji = "🔥" if quality == "Висока" else "🟢"
        text = f"{emoji} 📈 ВГОРУ (CALL)"
        if "Відскік" in reason[0]:
            text = f"{emoji} ЗОНА ПІДТРИМКИ: 📈 ВГОРУ (CALL)"
    else:
        emoji = "🔥" if quality == "Висока" else "🔴"
        text = f"{emoji} 📉 ВНИЗ (PUT)"
        if "Відскік" in reason[0]:
            text = f"{emoji} ЗОНА ОПОРУ: 📉 ВНИЗ (PUT)"

    details = (
        f"Актив: {analysis.symbol if hasattr(analysis, 'symbol') else ''} | "
        f"Ціна: {round(close, 5)} | RSI: {rsi} | Stoch: {stoch_k} | ADX: {adx} | "
        f"Якість: {quality} | {reason[0]}"
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
        # Основний аналіз
        analysis = get_safe_analysis(symbol, screener, exchange, interval)
        if not analysis:
            raise Exception("Не вдалося отримати аналіз")

        time.sleep(random.uniform(0.15, 0.35))

        # 15м
        higher_15 = None
        try:
            higher_15 = get_safe_analysis(symbol, screener, exchange, Interval.INTERVAL_15_MINUTES, retries=2)
        except:
            pass

        time.sleep(random.uniform(0.15, 0.3))

        # 1H
        higher_1h = None
        try:
            higher_1h = get_safe_analysis(symbol, screener, exchange, Interval.INTERVAL_1_HOUR, retries=2)
        except:
            pass

        signal_text, quality, details = calculate_signal_quality(analysis, higher_15, higher_1h)

        # Якщо SKIP — повертаємо нейтральний
        if signal_text == "SKIP":
            return jsonify({
                'signal': "⚪️ ⚖️ НЕМАЄ ЧІТКОГО СЕТАПУ — УТРИМАТИСЬ",
                'price': str(round(analysis.indicators.get("close", 0), 5)),
                'details': details,
                'quality': quality
            })

        return jsonify({
            'signal': signal_text,
            'price': str(round(analysis.indicators.get("close", 0), 5)),
            'details': details,
            'quality': quality
        })

    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
            'price': "--",
            'details': f"Спробуйте ще раз через 10-15 сек. ({str(e)[:40]})",
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
    return jsonify({'wins': row[0] if row else 0, 'losses': row[1] if row else 0})

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
        if result_type == 'win':
            wins += 1
        else:
            losses += 1
        cursor.execute(
            'UPDATE stats SET wins = ?, losses = ?, last_update = ? WHERE user_id = ?',
            (wins, losses, datetime.utcnow().isoformat(), user_id)
        )
    else:
        wins = 1 if result_type == 'win' else 0
        losses = 0 if result_type == 'win' else 1
        cursor.execute(
            'INSERT INTO stats (user_id, wins, losses, last_update) VALUES (?, ?, ?, ?)',
            (user_id, wins, losses, datetime.utcnow().isoformat())
        )

    conn.commit()
    conn.close()
    return jsonify({'wins': wins, 'losses': losses})

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    data = request.get_json() or {}
    user_id = str(data.get('user_id', 'default_user'))
    conn = sqlite3.connect('trading_stats.db')
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE stats SET wins = 0, losses = 0, last_update = ? WHERE user_id = ?',
        (datetime.utcnow().isoformat(), user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'wins': 0, 'losses': 0})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
