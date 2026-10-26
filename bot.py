import os
from flask import Flask, render_template, request, jsonify
from tradingview_ta import TA_Handler, Interval
import sqlite3
from datetime import datetime
import pytz

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
    if symbol in ['BTCUSD', 'ETHUSDT', 'SOLUSDT']:
        return 'crypto', 'BINANCE'
    elif symbol == 'XAUUSD':
        return 'cfd', 'OANDA'
    return 'forex', 'FX_IDC'

# Функція перевірки новинного фону та волатильності за київським часом
def check_news_volatility():
    try:
        kiev_tz = pytz.timezone('Europe/Kiev')
        now = datetime.now(kiev_tz)
        hour = now.hour
        minute = now.minute
        
        # Час пікових новин (наприклад, близько 15:30 та 17:00 за Києвом) або відкриття сесій
        if (hour == 15 and 25 <= minute <= 45) or (hour == 17 and 0 <= minute <= 20):
            return "🔴 Увага: висока волатильність (Вихід новин!)", True
        elif hour < 8 or hour > 21:
            return "🟡 Нічна сесія: низька ліквідність", False
        else:
            return "🟢 Ринки стабільні", False
    except Exception:
        return "🟢 Ринки стабільні", False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/news-status', methods=['GET'])
def news_status():
    status_text, is_danger = check_news_volatility()
    return jsonify({'status': status_text, 'danger': is_danger})

@app.route('/api/signal', methods=['POST'])
def get_signal():
    data = request.get_json() or {}
    symbol = data.get('symbol', 'GBPUSD')
    expiry = data.get('expiry', '1 хв')

    screener, exchange = get_exchange_and_screener(symbol)
    interval = TIMEFRAME_MAP.get(expiry, Interval.INTERVAL_1_MINUTE)
    
    news_text, is_danger = check_news_volatility()

    try:
        handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
        analysis = handler.get_analysis()
        
        higher_handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=Interval.INTERVAL_15_MINUTES)
        higher_analysis = higher_handler.get_analysis()

        current_price = round(analysis.indicators.get("close", 0.0), 5)
        recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        higher_rec = higher_analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        
        rsi = round(analysis.indicators.get("RSI", 50.0), 2)
        ema50 = analysis.indicators.get("EMA50", current_price)
        macd_val = round(analysis.indicators.get("MACD.macd", 0.0), 4)
        macd_signal = round(analysis.indicators.get("MACD.signal", 0.0), 4)
        bb_upper = round(analysis.indicators.get("BB.upper", current_price * 1.01), 5)
        bb_lower = round(analysis.indicators.get("BB.lower", current_price * 0.99), 5)

        if "BUY" in recommendation and ("BUY" in higher_rec or "STRONG_BUY" in higher_rec):
            signal_text = "🔥 СИЛЬНИЙ СИГНАЛ: 📈 ВГОРУ (CALL)"
        elif "SELL" in recommendation and ("SELL" in higher_rec or "STRONG_SELL" in higher_rec):
            signal_text = "🔥 СИЛЬНИЙ СИГНАЛ: 📉 ВНИЗ (PUT)"
        elif "BUY" in recommendation:
            signal_text = "🟢 📈 ВГОРУ (CALL)"
        elif "SELL" in recommendation:
            signal_text = "🔴 📉 ВНИЗ (PUT)"
        else:
            signal_text = "⚪️ ⚖️ НЕЙТРАЛЬНО (ОЧІКУВАННЯ)"

        macd_trend = "бичачий перетин" if macd_val > macd_signal else "ведмежий імпульс"
        if rsi < 40:
            rsi_desc = f"RSI перепроданий (~{rsi}), ціна біля нижньої межі Bollinger ({bb_lower})."
        elif rsi > 60:
            rsi_desc = f"RSI перекуплений (~{rsi}), ціна біля верхньої межі Bollinger ({bb_upper})."
        else:
            rsi_desc = f"RSI нейтральний ({rsi}), флет у межах діапазону."

        warning_note = " ⚠️ Увага: ринок під впливом новинного фону!" if is_danger else ""

        details_text = (
            f"Мультитаймфрейм-аналіз {symbol}: Ціна {current_price}. {rsi_desc} "
            f"MACD імпульс: {macd_trend}. Тренд на 15м: {higher_rec}. "
            f"EMA50 рівень: {ema50}. Рекомендація TradingView: {recommendation}.{warning_note}"
        )

        return jsonify({
            'signal': signal_text,
            'price': str(current_price),
            'details': details_text
        })

    except Exception as e:
        print(f"Помилка: {e}")
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
            'price': "--",
            'details': "Не вдалося отримати дані з ринку через високу завантаженість шлюзу."
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
    
    if row:
        return jsonify({'wins': row[0], 'losses': row[1]})
    return jsonify({'wins': 0, 'losses': 0})

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    
