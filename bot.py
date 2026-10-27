import os
import time
import random
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
            losses INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Робочі таймфрейми (змінили 15 хв на 10 хв)
TIMEFRAME_MAP = {
    '5 хв': Interval.INTERVAL_5_MINUTES,
    '10 хв': Interval.INTERVAL_10_MINUTES,
    '30 хв': Interval.INTERVAL_30_MINUTES,
    '1 год': Interval.INTERVAL_1_HOUR,
}

def get_exchange_and_screener(symbol):
    symbol = symbol.upper()
    if symbol == 'XAUUSD':
        return 'cfd', 'OANDA'
    return 'forex', 'FX_IDC'

def get_safe_analysis(symbol, screener, exchange, interval, retries=3):
    for attempt in range(retries):
        try:
            handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
            return handler.get_analysis()
        except Exception as e:
            if attempt == retries - 1:
                raise e
            sleep_time = (attempt + 1) * 2.0 + random.uniform(0.5, 1.5)
            time.sleep(sleep_time)

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
        # 1. Аналіз робочого таймфрейму
        analysis = get_safe_analysis(symbol, screener, exchange, interval)
        time.sleep(random.uniform(0.2, 0.4))

        # 2. Аналіз 10-хвилинного тренду (оптимально для 5м експірацій)
        higher_rec = "NEUTRAL"
        try:
            higher = get_safe_analysis(symbol, screener, exchange, Interval.INTERVAL_10_MINUTES, retries=2)
            higher_rec = higher.summary.get("RECOMMENDATION", "NEUTRAL")
        except Exception:
            pass

        # 3. Аналіз 1-годинного тренду для глобального напрямку
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
        
        is_bullish_macd = macd >= macd_signal
        higher_bull = "BUY" in higher_rec or "STRONG_BUY" in higher_rec
        higher_bear = "SELL" in higher_rec or "STRONG_SELL" in higher_rec
        h1_bull = "BUY" in h1_rec

        # Визначення зон підтримки та опору
        is_near_support = rsi < 42 or stoch_k < 28
        is_near_resistance = rsi > 58 or stoch_k > 72

        # Логіка входів з урахуванням 10м тренду та зон
        is_call = (
            (is_near_support and is_bullish_macd) or 
            ("BUY" in recommendation and not higher_bear)
        )
        
        is_put = (
            (is_near_resistance and not is_bullish_macd) or 
            ("SELL" in recommendation and not higher_bull)
        )

        if is_call and not is_put:
            if is_near_support:
                signal_text = "🔥 ЗОНА ПІДТРИМКИ: 📈 ВГОРУ (CALL - відскік)"
                quality = "Висока (Реакція від мінімуму)"
            else:
                signal_text = "🟢 📈 ВГОРУ (CALL - по тренду)"
                quality = "Стандартна"
        elif is_put and not is_call:
            if is_near_resistance:
                signal_text = "🔥 ЗОНА ОПОРУ: 📉 ВНИЗ (PUT - відскік)"
                quality = "Висока (Реакція від максимуму)"
            else:
                signal_text = "🔴 📉 ВНИЗ (PUT - по тренду)"
                quality = "Стандартна"
        else:
            signal_text = "⚪️ ⚖️ РИНКОВИЙ ФЛЕТ: УТРИМАТИСЬ"
            quality = "Поза зоною інтересу"

        rsi_status = "перекупленість" if rsi > 70 else ("перепроданість" if rsi < 30 else "робоча зона")
        trend_10 = "висхідний" if higher_bull else ("низхідний" if higher_bear else "нейтральний")

        details_text = (
            f"Актив: {symbol} | Ціна: {current_price} | RSI: {rsi} ({rsi_status}) | "
            f"Stoch K: {stoch_k} | Зона: {'Підтримка' if is_near_support else ('Опір' if is_near_resistance else 'Середина')} | "
            f"Тренд 10м: {trend_10} | Якість: {quality}"
        )

        return jsonify({'signal': signal_text, 'price': str(current_price), 'details': details_text})

    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ", 
            'price': "--", 
            'details': f"Захист шлюзу. Спробуйте ще раз. ({str(e)[:30]})"
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
        if result_type == 'win': wins += 1
        else: losses += 1
        cursor.execute('UPDATE stats SET wins = ?, losses = ? WHERE user_id = ?', (wins, losses, user_id))
    else:
        wins = 1 if result_type == 'win' else 0
        losses = 0 if result_type == 'win' else 1
        cursor.execute('INSERT INTO stats (user_id, wins, losses) VALUES (?, ?, ?)', (user_id, wins, losses))
        
    conn.commit()
    conn.close()
    return jsonify({'wins': wins, 'losses': losses})

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    data = request.get_json() or {}
    user_id = str(data.get('user_id', 'default_user'))
    conn = sqlite3.connect('trading_stats.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE stats SET wins = 0, losses = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'wins': 0, 'losses': 0})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    
