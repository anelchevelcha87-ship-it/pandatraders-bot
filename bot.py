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

TIMEFRAME_MAP = {
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

def get_safe_analysis(symbol, screener, exchange, interval, retries=3):
    for attempt in range(retries):
        try:
            handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
            return handler.get_analysis()
        except Exception as e:
            if attempt == retries - 1:
                raise e
            sleep_time = (attempt + 1) * 2.5 + random.uniform(1.0, 2.0)
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
        analysis = get_safe_analysis(symbol, screener, exchange, interval)
        time.sleep(random.uniform(0.4, 0.8))

        current_price = round(analysis.indicators.get("close", 0.0), 5)
        recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        
        rsi = round(analysis.indicators.get("RSI", 50.0), 2)
        macd_val = round(analysis.indicators.get("MACD.macd", 0.0), 4)
        macd_signal = round(analysis.indicators.get("MACD.signal", 0.0), 4)
        stoch_k = round(analysis.indicators.get("Stoch.K", 50.0), 2)
        
        rsi_status = "перекупленість (>70)" if rsi > 70 else ("перепроданість (<30)" if rsi < 30 else "робоча зона")
        is_bullish_macd = macd_val >= macd_signal

        is_buy = "BUY" in recommendation or "STRONG_BUY" in recommendation or (is_bullish_macd and rsi < 65)
        is_sell = "SELL" in recommendation or "STRONG_SELL" in recommendation or (not is_bullish_macd and rsi > 35)

        if is_buy and not is_sell:
            signal_text = "🔥 СИГНАЛ: 📈 ВГОРУ (CALL)"
        elif is_sell and not is_buy:
            signal_text = "🔥 СИГНАЛ: 📉 ВНИЗ (PUT)"
        else:
            if "BUY" in recommendation:
                signal_text = "🟢 📈 ВГОРУ (CALL - по тренду)"
            elif "SELL" in recommendation:
                signal_text = "🔴 📉 ВНИЗ (PUT - по тренду)"
            else:
                signal_text = "⚪️ ⚖️ РИНКОВИЙ ФЛЕТ (Нейтрально)"

        details_text = (
            f"Актив: {symbol} | Ціна: {current_price} | RSI: {rsi} ({rsi_status}). "
            f"Stoch %K: {stoch_k} | MACD: {'бичачий' if is_bullish_macd else 'ведмежий'}. "
            f"Рекомендація: {recommendation}."
        )

        return jsonify({'signal': signal_text, 'price': str(current_price), 'details': details_text})

    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ", 
            'price': "--", 
            'details': f"Захист від частоти запитів. Зачекайте 5 сек. ({str(e)[:35]})"
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
    
