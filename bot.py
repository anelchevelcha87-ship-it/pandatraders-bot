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

def get_safe_analysis(symbol, screener, exchange, interval, retries=3):
    """Безпечний запит із рандомізованою затримкою для обходу блокувань Cloudflare"""
    for attempt in range(retries):
        try:
            handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
            return handler.get_analysis()
        except Exception as e:
            if attempt == retries - 1:
                raise e
            # Збільшуємо паузу з кожною спробою та додаємо випадковий час (виглядає як людина)
            sleep_time = (attempt + 1) * 2 + random.uniform(0.5, 1.5)
            time.sleep(sleep_time)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/signal', methods=['POST'])
def get_signal():
    data = request.get_json() or {}
    symbol = data.get('symbol', 'GBPUSD')
    expiry = data.get('expiry', '5 хв')

    screener, exchange = get_exchange_and_screener(symbol)
    interval = TIMEFRAME_MAP.get(expiry, Interval.INTERVAL_5_MINUTES)

    try:
        # Отримуємо аналіз робочого таймфрейму
        analysis = get_safe_analysis(symbol, screener, exchange, interval)
        
        # Легке гальмування між запитами, щоб не тригерити захист шлюзу
        time.sleep(random.uniform(0.3, 0.7))

        # Безпечний запит на старший таймфрейм (15 хв)
        higher_rec = "NEUTRAL"
        try:
            higher_analysis = get_safe_analysis(symbol, screener, exchange, Interval.INTERVAL_15_MINUTES, retries=2)
            higher_rec = higher_analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        except Exception:
            pass 

        current_price = round(analysis.indicators.get("close", 0.0), 5)
        recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        
        rsi = round(analysis.indicators.get("RSI", 50.0), 2)
        macd_val = round(analysis.indicators.get("MACD.macd", 0.0), 4)
        macd_signal = round(analysis.indicators.get("MACD.signal", 0.0), 4)
        stoch_k = round(analysis.indicators.get("Stoch.K", 50.0), 2)
        stoch_d = round(analysis.indicators.get("Stoch.D", 50.0), 2)
        
        rsi_status = "перекупленість (>70)" if rsi > 70 else ("перепроданість (<30)" if rsi < 30 else "стабільна робоча зона")
        trend_desc = "висхідний тренд (BUY)" if "BUY" in higher_rec else ("низхідний тренд (SELL)" if "SELL" in higher_rec else "боковий рух (нейтрально)")
        
        is_bullish_macd = macd_val >= macd_signal
        is_bearish_macd = macd_val < macd_signal

        # Покращена фільтрація для 5 хв
        if ("BUY" in recommendation or "STRONG_BUY" in recommendation) and is_bullish_macd and rsi < 75 and stoch_k < 85:
            if "BUY" in higher_rec:
                signal_text = "🔥 ТОЧНИЙ СИГНАЛ: 📈 ВГОРУ (CALL)"
            else:
                signal_text = "🟢 📈 ВГОРУ (CALL - помірний сигнал)"
        elif ("SELL" in recommendation or "STRONG_SELL" in recommendation) and is_bearish_macd and rsi > 25 and stoch_k > 15:
            if "SELL" in higher_rec:
                signal_text = "🔥 ТОЧНИЙ СИГНАЛ: 📉 ВНИЗ (PUT)"
            else:
                signal_text = "🔴 📉 ВНИЗ (PUT - помірний сигнал)"
        else:
            signal_text = "⚪️ ⚖️ ФІЛЬТР РИНКУ: УТРИМАТИСЬ ВІД УГОДИ"

        details_text = (
            f"Ціна: {current_price} | RSI: {rsi} ({rsi_status}). "
            f"Стохастик (%K: {stoch_k}, %D: {stoch_d}) | MACD імпульс: {'бичачий' if is_bullish_macd else 'ведмежий'}. "
            f"Глобальний контекст (15хв): {trend_desc}. "
            f"Статус шлюзу: стабільне з'єднання."
        )

        return jsonify({'signal': signal_text, 'price': str(current_price), 'details': details_text})

    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ", 
            'price': "--", 
            'details': f"Захист шлюзу тимчасово обмежив запити. Зачекайте хвилину. ({str(e)[:30]})"
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
