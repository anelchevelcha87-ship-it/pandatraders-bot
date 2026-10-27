
import os
import time
import random
from flask import Flask, render_template, request, jsonify
from tradingview_ta import TA_Handler, Interval
import sqlite3

app = Flask(name, template_folder='templates')

def init_db():
    conn = sqlite3.connect('trading_stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            user_id TEXT PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

TIMEFRAME_MAP = {
    '1 хв': Interval.INTERVAL_1_MINUTE,
    '5 хв': Interval.INTERVAL_5_MINUTES,
    '15 хв': Interval.INTERVAL_15_MINUTES,
    '30 хв': Interval.INTERVAL_30_MINUTES,
    '1 год': Interval.INTERVAL_1_HOUR,
}

def get_exchange_and_screener(symbol):
    symbol = symbol.upper()
    if symbol == 'XAUUSD':
        return 'cfd', 'OANDA'
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
            return handler.get_analysis()
        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep((attempt + 1) * 1.7 + random.uniform(0.3, 1.1))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/signal', methods=['POST'])
def get_signal():
    data = request.get_json() or {}
    symbol = data.get('symbol', 'GBPUSD').upper()
    expiry = data.get('expiry', '5 хв')

    screener, exchange = get_exchange_and_screener(symbol)
    interval = TIMEFRAME_MAP.get(expiry, Interval.INTERVAL_5_MINUTES)

    try:
        analysis = get_safe_analysis(symbol, screener, exchange, interval)
        time.sleep(random.uniform(0.25, 0.5))

        # 15-хвилинний ТФ (обов'язковий фільтр)
        higher_rec = "NEUTRAL"
        try:
            higher = get_safe_analysis(symbol, screener, exchange, Interval.INTERVAL_15_MINUTES, retries=3)
            higher_rec = higher.summary.get("RECOMMENDATION", "NEUTRAL")
        except Exception:
            pass

        # 1-годинний ТФ (бажаний)
        h1_rec = "NEUTRAL"
        try:
            h1 = get_safe_analysis(symbol, screener, exchange, Interval.INTERVAL_1_HOUR, retries=2)
            h1_rec = h1.summary.get("RECOMMENDATION", "NEUTRAL")
        except Exception:
            pass

        ind = analysis.indicators
        recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")

        current_price = round(ind.get("close", 0.0), 5)
        rsi = round(ind.get("RSI", 50.0), 2)
        macd = round(ind.get("MACD.macd", 0.0), 5)
        macd_signal = round(ind.get("MACD.signal", 0.0), 5)
        stoch_k = round(ind.get("Stoch.K", 50.0), 2)
        stoch_d = round(ind.get("Stoch.D", 50.0), 2)
        adx = ind.get("ADX")
        ema20 = ind.get("EMA20")
        ema50 = ind.get("EMA50")

        is_bullish_macd = macd > macd_signal
        is_bearish_macd = macd < macd_signal

        higher_bull = "BUY" in higher_rec
        higher_bear = "SELL" in higher_rec
        h1_bull = "BUY" in h1_rec
        h1_bear = "SELL" in h1_rec

        # EMA підтвердження
        ema_ok_buy = True
        ema_ok_sell = True
        if ema20 is not None and ema50 is not None:
            ema_ok_buy = ema20 >= ema50
            ema_ok_sell = ema20 <= ema50

        # ADX
        strong_trend = True
        if adx is not None:
            strong_trend = adx >= 18

        # ====================== УМОВИ СИГНАЛУ ======================
        is_strong_buy = (
            recommendation in ["STRONG_BUY", "BUY"] and
            higher_bull and
            is_bullish_macd and
            28 < rsi < 65 and
            stoch_k < 80 and
            stoch_d < 80 and
            strong_trend and
            ema_ok_buy
        )

is_strong_sell = (
            recommendation in ["STRONG_SELL", "SELL"] and
            higher_bear and
            is_bearish_macd and
            35 < rsi < 72 and
            stoch_k > 20 and
            stoch_d > 20 and
            strong_trend and
            ema_ok_sell
        )

        # Формування сигналу
        if is_strong_buy and h1_bull:
            confidence = "ДУЖЕ ВИСОКА"
            signal_text = "🔥 СИЛЬНИЙ СИГНАЛ: 📈 ВГОРУ (CALL)"
        elif is_strong_sell and h1_bear:
            confidence = "ДУЖЕ ВИСОКА"
            signal_text = "🔥 СИЛЬНИЙ СИГНАЛ: 📉 ВНИЗ (PUT)"
        elif is_strong_buy:
            confidence = "ВИСОКА"
            signal_text = "🔥 СИЛЬНИЙ СИГНАЛ: 📈 ВГОРУ (CALL)"
        elif is_strong_sell:
            confidence = "ВИСОКА"
            signal_text = "🔥 СИЛЬНИЙ СИГНАЛ: 📉 ВНИЗ (PUT)"
        else:
            signal_text = "⚪️ НЕМАЄ ВПЕВНЕНОГО СИГНАЛУ"
            confidence = "—"

        rsi_status = (
            "перекупленість" if rsi > 70 else
            "перепроданість" if rsi < 30 else
            "робоча зона"
        )
        trend_15 = "висхідний" if higher_bull else ("низхідний" if higher_bear else "нейтральний")
        trend_1h = "висхідний" if h1_bull else ("низхідний" if h1_bear else "нейтральний")

        details_text = (
            f"Актив: {symbol} | Ціна: {current_price} | "
            f"RSI: {rsi} ({rsi_status}) | "
            f"Stoch: {stoch_k}/{stoch_d} | "
            f"MACD: {'бичачий' if is_bullish_macd else 'ведмежий'} | "
            f"Тренд 15м: {trend_15} | Тренд 1г: {trend_1h} | "
            f"Впевненість: {confidence}"
        )

        return jsonify({
            'signal': signal_text,
            'price': str(current_price),
            'details': details_text
        })

    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
            'price': "--",
            'details': f"Тимчасовий ліміт. Спробуйте ще раз. ({str(e)[:45]})"
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
    return jsonify({
        'wins': row[0] if row else 0,
        'losses': row[1] if row else 0
    })

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
            'UPDATE stats SET wins = ?, losses = ? WHERE user_id = ?',
            (wins, losses, user_id)
        )
    else:
        wins = 1 if result_type == 'win' else 0
        losses = 0 if result_type == 'win' else 1
        cursor.execute(
            'INSERT INTO stats (user_id, wins, losses) VALUES (?, ?, ?)',
            (user_id, wins, losses)
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
        'UPDATE stats SET wins = 0, losses = 0 WHERE user_id = ?',
        (user_id,)
    )
    conn.commit()
    conn.close()
    return jsonify({'wins': 0, 'losses': 0})

if name == 'main':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
