import os
from flask import Flask, render_template, request, jsonify
from tradingview_ta import TA_Handler, Interval

app = Flask(__name__, template_folder='templates')

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/signal', methods=['POST'])
def get_signal():
    data = request.get_json() or {}
    symbol = data.get('symbol', 'GBPUSD')
    expiry = data.get('expiry', '1 хв')

    screener, exchange = get_exchange_and_screener(symbol)
    interval = TIMEFRAME_MAP.get(expiry, Interval.INTERVAL_1_MINUTE)

    try:
        handler = TA_Handler(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
        analysis = handler.get_analysis()

        current_price = round(analysis.indicators.get("close", 0.0), 5)
        recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
        rsi = round(analysis.indicators.get("RSI", 50.0), 2)
        ema50 = analysis.indicators.get("EMA50", current_price)

        if "BUY" in recommendation:
            signal_text = "🟢 ВГОРУ (CALL)"
        elif "SELL" in recommendation:
            signal_text = "🔴 ВНИЗ (PUT)"
        else:
            signal_text = "⚪️ НЕЙТРАЛЬНО (ОЧІКУВАННЯ)"

        if rsi < 40:
            rsi_desc = f"Індикатор RSI знаходиться в зоні перепроданості (~{rsi}), можливий відскік ціни вгору."
        elif rsi > 60:
            rsi_desc = f"Індикатор RSI знаходиться в зоні перекупленості (~{rsi}), можливий розворот вниз."
        else:
            rsi_desc = f"Ринковий індикатор RSI знаходиться на нейтральній позначці ({rsi}), чіткого тренду немає."

        details_text = (
            f"Аналіз ринку: Ціна на активі {symbol} складає {current_price}. "
            f"{rsi_desc} Рекомендація технічних індикаторів TradingView: {recommendation}. "
            f"Експертний висновок: зважайте на поточну волатильність та рівень EMA50 ({ema50})."
        )

        return jsonify({
            'signal': signal_text,
            'price': str(current_price),
            'details': details_text
        })

    except Exception as e:
        print(f"Помилка: {e}")
        return jsonify({
            'signal': "⚠️ ПОМИЛКА",
            'price': "--",
            'details': "Не вдалося отримати дані з ринку. Спробуйте ще раз."
        })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    
