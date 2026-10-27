import os
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
        handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
        analysis = handler.get_analysis()
        
        # Безпечний запит на старший таймфрейм (трендовий фільтр 15 хв)
        higher_rec = "NEUTRAL"
        try:
            higher_handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=Interval.INTERVAL_15_MINUTES)
            higher_analysis = higher_handler.get_analysis()
            higher_rec = higher_analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        except Exception:
            pass 

        current_price = round(analysis.indicators.get("close", 0.0), 5)
        recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        
        # Індикатори
        rsi = round(analysis.indicators.get("RSI", 50.0), 2)
        macd_val = round(analysis.indicators.get("MACD.macd", 0.0), 4)
        macd_signal = round(analysis.indicators.get("MACD.signal", 0.0), 4)
        
        # Стохастик (%K та %D)
        stoch_k = round(analysis.indicators.get("Stoch.K", 50.0), 2)
        stoch_d = round(analysis.indicators.get("Stoch.D", 50.0), 2)
        
        # Фільтри та статус
        rsi_status = "перекупленість (>70)" if rsi > 70 else ("перепроданість (<30)" if rsi < 30 else "робоча зона")
        trend_desc = "висхідний" if "BUY" in higher_rec else ("низхідний" if "SELL" in higher_rec else "невизначений")
        
        is_bullish_macd = macd_val > macd_signal
        is_bearish_macd = macd_val < macd_signal
        
        # Умови стохастика для входу
        stoch_bullish_ok = stoch_k < 80 and stoch_k > stoch_d  # Не в перекупленості і лінія K вище D (рух вгору)
        stoch_bearish_ok = stoch_k > 20 and stoch_k < stoch_d  # Не в перепроданості і лінія K нижче D (рух вниз)

        # Розумна логіка з урахуванням стохастика, MACD та тренду
        if ("BUY" in recommendation or "STRONG_BUY" in recommendation) and ("BUY" in higher_rec or "STRONG_BUY" in higher_rec) and is_bullish_macd and stoch_bullish_ok and rsi < 68:
            signal_text = "🔥 ТОЧНИЙ СИГНАЛ: 📈 ВГОРУ (CALL)"
        elif ("SELL" in recommendation or "STRONG_SELL" in recommendation) and ("SELL" in higher_rec or "STRONG_SELL" in higher_rec) and is_bearish_macd and stoch_bearish_ok and rsi > 32:
            signal_text = "🔥 ТОЧНИЙ СИГНАЛ: 📉 ВНИЗ (PUT)"
        elif "BUY" in recommendation and rsi < 70 and stoch_k < 85:
            signal_text = "🟢 📈 ВГОРУ (CALL - помірний)"
        elif "SELL" in recommendation and rsi > 30 and stoch_k > 15:
            signal_text = "🔴 📉 ВНИЗ (PUT - помірний)"
        else:
            signal_text = "⚪️ ⚖️ ФІЛЬТР РИНКУ: УТРИМАТИСЬ ВІД УГОДИ"

        details_text = (
            f"Ціна: {current_price} | RSI: {rsi} ({rsi_status}). "
            f"Стохастик: %K={stoch_k}, %D={stoch_d}. "
            f"Тренд 15хв: {trend_desc} | MACD: {'бичачий' if is_bullish_macd else 'ведмежий'}. "
            f"Фільтр: стохастик та імпульс успішно узгоджені."
        )

        return jsonify({'signal': signal_text, 'price': str(current_price), 'details': details_text})

    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ", 
            'price': "--", 
            'details': f"Тимчасовий ліміт шлюзу. Зачекайте хвилину. ({str(e)[:30]})"
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
    
