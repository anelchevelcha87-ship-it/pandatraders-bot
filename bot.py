import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request
from tradingview_ta import Interval, TA_Handler

app = Flask(__name__, template_folder='templates')

DB_PATH = os.environ.get('DB_PATH', 'trading_stats.db')
KYIV_TZ = ZoneInfo('Europe/Kyiv')


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                user_id TEXT PRIMARY KEY,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                last_update TEXT
            )
        ''')
        conn.commit()
    finally:
        conn.close()


init_db()

TIMEFRAME_MAP = {
    '5 хв': Interval.INTERVAL_5_MINUTES,
    '15 хв': Interval.INTERVAL_15_MINUTES,
    '30 хв': Interval.INTERVAL_30_MINUTES,
    '1 год': Interval.INTERVAL_1_HOUR,
}

HIGHER_TF_MAP = {
    '5 хв': Interval.INTERVAL_15_MINUTES,
    '15 хв': Interval.INTERVAL_1_HOUR,
    '30 хв': Interval.INTERVAL_1_HOUR,
    '1 год': Interval.INTERVAL_4_HOURS,
}

_cache = {}
CACHE_TTL = 60


def get_exchange_and_screener(symbol):
    symbol = (symbol or '').strip().upper()
    if symbol in {'XAUUSD', 'XAGUSD'}:
        return 'cfd', 'OANDA'
    return 'forex', 'FX_IDC'


def check_news_alert():
    now_kyiv = datetime.now(KYIV_TZ)
    h, m = now_kyiv.hour, now_kyiv.minute
    if (h == 14 and m >= 30) or (h in (15, 16)) or (h == 17 and m <= 30):
        return "⚠️ Увага: Час можливого виходу новин (висока волатильність)."
    return "✅ Новинний фон: Спокійно."


def get_safe_analysis(symbol, screener, exchange, interval, retries=2):
    key = f"{symbol}_{screener}_{exchange}_{interval}"
    now = time.time()

    cached = _cache.get(key)
    if cached:
        data, timestamp = cached
        if now - timestamp < CACHE_TTL:
            return data

    for attempt in range(retries):
        try:
            handler = TA_Handler(
                symbol=symbol,
                screener=screener,
                exchange=exchange,
                interval=interval,
            )
            analysis = handler.get_analysis()
            if analysis and analysis.indicators:
                _cache[key] = (analysis, now)
                return analysis
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(0.5 * (attempt + 1) + random.uniform(0.1, 0.3))

    return None


def calculate_signal(analysis, higher_tf=None):
    ind = analysis.indicators
    rec = analysis.summary.get("RECOMMENDATION", "NEUTRAL")

    rsi = round(float(ind.get("RSI", 50)), 2)
    stoch_k = round(float(ind.get("Stoch.K", 50)), 2)
    macd = float(ind.get("MACD.macd", 0))
    macd_signal = float(ind.get("MACD.signal", 0))
    adx = round(float(ind.get("ADX", 20)), 2)
    close = float(ind.get("close", 0))
    bb_upper = float(ind.get("BB.upper", close if close else 1))
    bb_lower = float(ind.get("BB.lower", close if close else 0))

    is_bull_macd = macd > macd_signal
    is_bear_macd = macd < macd_signal
    strong_trend = adx >= 18

    near_support = (rsi < 40 and stoch_k < 30) or (close > 0 and close <= bb_lower * 1.002)
    near_resistance = (rsi > 60 and stoch_k > 70) or (close > 0 and close >= bb_upper * 0.998)

    higher_rec = "NEUTRAL"
    if higher_tf and hasattr(higher_tf, 'summary'):
        higher_rec = higher_tf.summary.get("RECOMMENDATION", "NEUTRAL")

    higher_bear = "SELL" in higher_rec or "STRONG_SELL" in higher_rec
    higher_bull = "BUY" in higher_rec or "STRONG_BUY" in higher_rec

    signal = None
    quality = "Середня"
    reasons = []

    if near_support and is_bull_macd and not higher_bear:
        signal = "CALL"
        quality = "Висока" if strong_trend else "Середня"
        reasons.append("Відскік від підтримки")
    elif ("BUY" in rec or "STRONG_BUY" in rec) and is_bull_macd and not higher_bear and rsi < 68:
        signal = "CALL"
        quality = "Висока" if adx >= 24 else "Середня"
        reasons.append("Тренд вгору")
    elif near_resistance and is_bear_macd and not higher_bull:
        signal = "PUT"
        quality = "Висока" if strong_trend else "Середня"
        reasons.append("Відскік від опору")
    elif ("SELL" in rec or "STRONG_SELL" in rec) and is_bear_macd and not higher_bull and rsi > 32:
        signal = "PUT"
        quality = "Висока" if adx >= 24 else "Середня"
        reasons.append("Тренд вниз")

    news_status = check_news_alert()

    if not signal:
        return (
            "⚪️ ⚖️ РИНКОВИЙ ФЛЕТ — УТРИМАТИСЬ",
            "Низька",
            f"Флет / Немає сетапу | RSI: {rsi} | {news_status}",
        )

    reason_text = reasons[0] if reasons else "Підтвердження індикаторів"

    if signal == "CALL":
        emoji = "🔥" if quality == "Висока" else "🟢"
        text = (
            f"{emoji} ЗОНА ПІДТРИМКИ: 📈 ВГОРУ (CALL)"
            if "підтримки" in reason_text.lower()
            else f"{emoji} 📈 ВГОРУ (CALL)"
        )
    else:
        emoji = "🔥" if quality == "Висока" else "🔴"
        text = (
            f"{emoji} ЗОНА ОПОРУ: 📉 ВНИЗ (PUT)"
            if "опору" in reason_text.lower()
            else f"{emoji} 📉 ВНИЗ (PUT)"
        )

    details = (
        f"Ціна: {round(close, 5)} | RSI: {rsi} | Stoch: {stoch_k} | ADX: {adx} | "
        f"Якість: {quality} | {reason_text} | {news_status}"
    )

    return text, quality, details


def format_stats_response(wins, losses):
    total = wins + losses
    winrate = round((wins / total * 100), 1) if total > 0 else 0.0
    return jsonify({
        'wins': wins,
        'losses': losses,
        'total': total,
        'winrate': winrate,
    })


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/signal', methods=['POST'])
def get_signal():
    data = request.get_json(silent=True) or {}
    symbol = (data.get('symbol') or 'EURUSD').strip().upper()
    expiry = data.get('expiry') or '5 хв'

    if not symbol:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА ВВОДУ",
            'price': "--",
            'details': "Не вказано торгову пару.",
            'quality': "Помилка",
        }), 400

    screener, exchange = get_exchange_and_screener(symbol)
    interval = TIMEFRAME_MAP.get(expiry, Interval.INTERVAL_5_MINUTES)
    higher_interval = HIGHER_TF_MAP.get(expiry, Interval.INTERVAL_15_MINUTES)

    try:
        analysis = get_safe_analysis(symbol, screener, exchange, interval)
        if not analysis:
            return jsonify({
                'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
                'price': "--",
                'details': "TradingView тимчасово не відповів. Спробуйте ще раз за кілька секунд.",
                'quality': "Помилка",
            })

        higher_tf = None
        try:
            higher_tf = get_safe_analysis(symbol, screener, exchange, higher_interval, retries=1)
        except Exception:
            higher_tf = None

        signal_text, quality, details = calculate_signal(analysis, higher_tf)
        close_price = str(round(float(analysis.indicators.get("close", 0)), 5))

        return jsonify({
            'signal': signal_text,
            'price': close_price,
            'details': details,
            'quality': quality,
        })
    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
            'price': "--",
            'details': f"Збій обробки запиту: {str(e)[:40]}",
            'quality': "Помилка",
        })


@app.route('/api/stats/get', methods=['POST'])
def get_stats():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or 'default_user').strip()

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT wins, losses FROM stats WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
    finally:
        conn.close()

    wins = int(row['wins']) if row else 0
    losses = int(row['losses']) if row else 0
    return format_stats_response(wins, losses)


@app.route('/api/stats/update', methods=['POST'])
def update_stats():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or 'default_user').strip()
    result_type = (data.get('type') or 'win').lower()

    if result_type not in {'win', 'loss'}:
        return jsonify({'error': "Некоректний тип результату (очікується 'win' або 'loss')"}), 400

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT wins, losses FROM stats WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()

        if row:
            wins = int(row['wins']) + (1 if result_type == 'win' else 0)
            losses = int(row['losses']) + (1 if result_type == 'loss' else 0)
            cursor.execute(
                'UPDATE stats SET wins = ?, losses = ?, last_update = ? WHERE user_id = ?',
                (wins, losses, now_iso, user_id),
            )
        else:
            wins = 1 if result_type == 'win' else 0
            losses = 1 if result_type == 'loss' else 0
            cursor.execute(
                'INSERT INTO stats (user_id, wins, losses, last_update) VALUES (?, ?, ?, ?)',
                (user_id, wins, losses, now_iso),
            )
        conn.commit()
    finally:
        conn.close()

    return format_stats_response(wins, losses)


@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or 'default_user').strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO stats (user_id, wins, losses, last_update)
            VALUES (?, 0, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                wins = 0,
                losses = 0,
                last_update = excluded.last_update
            ''',
            (user_id, now_iso),
        )
        conn.commit()
    finally:
        conn.close()

    return format_stats_response(0, 0)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
    
