import os
import time
import random
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import sqlite3
from functools import lru_cache

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

# Мапінг символів під Yahoo Finance
SYMBOL_MAP = {
    'EURUSD': 'EURUSD=X',
    'GBPUSD': 'GBPUSD=X',
    'USDJPY': 'USDJPY=X',
    'USDCHF': 'USDCHF=X',
    'AUDUSD': 'AUDUSD=X',
    'USDCAD': 'USDCAD=X',
    'NZDUSD': 'NZDUSD=X',
    'EURGBP': 'EURGBP=X',
    'EURJPY': 'EURJPY=X',
    'GBPJPY': 'GBPJPY=X',
    'AUDJPY': 'AUDJPY=X',
    'CADJPY': 'CADJPY=X',
    'CHFJPY': 'CHFJPY=X',
    'EURAUD': 'EURAUD=X',
    'EURCHF': 'EURCHF=X',
    'GBPCHF': 'GBPCHF=X',
    'AUDCHF': 'AUDCHF=X',
    'AUDCAD': 'AUDCAD=X',
    'CADCHF': 'CADCHF=X',
    'GBPCAD': 'GBPCAD=X',
    'GBPAUD': 'GBPAUD=X',
    'XAUUSD': 'GC=F',      # Золото
    'XAGUSD': 'SI=F',      # Срібло
}

def get_yf_symbol(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}=X")

def fetch_data(symbol: str, interval: str = "5m", period: str = "5d"):
    """Завантажує дані з Yahoo"""
    yf_symbol = get_yf_symbol(symbol)
    try:
        df = yf.download(
            yf_symbol,
            interval=interval,
            period=period,
            progress=False,
            auto_adjust=True,
            prepost=False
        )
        if df.empty or len(df) < 50:
            return None
        
        # Якщо MultiIndex — спрощуємо
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df.dropna()
        return df
    except Exception as e:
        print(f"Помилка завантаження {symbol}: {e}")
        return None

def calculate_indicators(df: pd.DataFrame):
    """Рахуємо всі потрібні індикатори"""
    if df is None or len(df) < 50:
        return None

    df = df.copy()
    
    # RSI
    df['RSI'] = ta.rsi(df['Close'], length=14)
    
    # Stochastic
    stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=14, d=3, smooth_k=3)
    if stoch is not None:
        df['Stoch_K'] = stoch[f'STOCHk_14_3_3']
        df['Stoch_D'] = stoch[f'STOCHd_14_3_3']
    
    # MACD
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df['MACD'] = macd['MACD_12_26_9']
        df['MACD_signal'] = macd['MACDs_12_26_9']
        df['MACD_hist'] = macd['MACDh_12_26_9']
    
    # ADX
    adx = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    if adx is not None:
        df['ADX'] = adx['ADX_14']
    
    # Bollinger Bands
    bb = ta.bbands(df['Close'], length=20, std=2)
    if bb is not None:
        df['BB_upper'] = bb['BBU_20_2.0']
        df['BB_middle'] = bb['BBM_20_2.0']
        df['BB_lower'] = bb['BBL_20_2.0']
    
    # EMA
    df['EMA20'] = ta.ema(df['Close'], length=20)
    df['EMA50'] = ta.ema(df['Close'], length=50)
    
    return df.dropna()

def analyze_signal(symbol: str, expiry: str = "5 хв"):
    """Головна логіка сигналу під 5 хвилин"""
    
    # Основний таймфрейм
    df_5m = fetch_data(symbol, interval="5m", period="5d")
    df_5m = calculate_indicators(df_5m)
    
    if df_5m is None or len(df_5m) < 30:
        return None, None, "Не вдалося отримати дані 5м"
    
    # 15 хвилин
    df_15m = fetch_data(symbol, interval="15m", period="10d")
    df_15m = calculate_indicators(df_15m)
    
    # 1 година
    df_1h = fetch_data(symbol, interval="1h", period="30d")
    df_1h = calculate_indicators(df_1h)
    
    last = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    
    close = float(last['Close'])
    rsi = float(last['RSI'])
    stoch_k = float(last.get('Stoch_K', 50))
    adx = float(last.get('ADX', 20))
    macd = float(last.get('MACD', 0))
    macd_signal = float(last.get('MACD_signal', 0))
    bb_upper = float(last.get('BB_upper', close))
    bb_lower = float(last.get('BB_lower', close))
    
    # Вищі таймфрейми
    rsi_15 = float(df_15m.iloc[-1]['RSI']) if df_15m is not None and len(df_15m) > 0 else 50
    adx_15 = float(df_15m.iloc[-1].get('ADX', 20)) if df_15m is not None else 20
    macd_15_bull = False
    if df_15m is not None and len(df_15m) > 0:
        macd_15_bull = df_15m.iloc[-1].get('MACD', 0) > df_15m.iloc[-1].get('MACD_signal', 0)
    
    # Умови
    is_bull_macd = macd > macd_signal
    is_bear_macd = macd < macd_signal
    strong_trend = adx >= 22
    very_strong = adx >= 27
    
    near_support = (rsi < 38 and stoch_k < 28) or (close <= bb_lower * 1.0015)
    near_resistance = (rsi > 62 and stoch_k > 72) or (close >= bb_upper * 0.9985)
    
    # Мультитаймфрейм
    bull_mtf = rsi_15 < 65 and (macd_15_bull or adx_15 > 20)
    bear_mtf = rsi_15 > 35 and (not macd_15_bull or adx_15 > 20)
    
    signal = None
    quality = "Середня"
    reason = []
    
    # === CALL ===
    if near_support and is_bull_macd and strong_trend and bull_mtf:
        signal = "CALL"
        quality = "Висока"
        reason.append("Відскік від підтримки + ADX + 15м підтвердження")
    elif is_bull_macd and strong_trend and bull_mtf and rsi < 62 and close > last.get('EMA20', close):
        signal = "CALL"
        quality = "Висока" if very_strong else "Середня"
        reason.append("Тренд вгору + мульти-ТФ")
    elif near_support and is_bull_macd and rsi < 42:
        signal = "CALL"
        quality = "Середня"
        reason.append("Відскік від зони підтримки")
    
    # === PUT ===
    elif near_resistance and is_bear_macd and strong_trend and bear_mtf:
        signal = "PUT"
        quality = "Висока"
        reason.append("Відскік від опору + ADX + 15м підтвердження")
    elif is_bear_macd and strong_trend and bear_mtf and rsi > 38 and close < last.get('EMA20', close):
        signal = "PUT"
        quality = "Висока" if very_strong else "Середня"
        reason.append("Тренд вниз + мульти-ТФ")
    elif near_resistance and is_bear_macd and rsi > 58:
        signal = "PUT"
        quality = "Середня"
        reason.append("Відскік від зони опору")
    
    if not signal:
        return "SKIP", "Низька", f"Немає чіткого се сетапу | RSI: {rsi:.1f} | ADX: {adx:.1f}"
    
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
        f"Актив: {symbol} | Ціна: {close:.5f} | RSI: {rsi:.1f} | "
        f"Stoch: {stoch_k:.1f} | ADX: {adx:.1f} | Якість: {quality} | {reason[0]}"
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
    
    try:
        signal_text, quality, details = analyze_signal(symbol, expiry)
        
        if signal_text is None:
            return jsonify({
                'signal': "⚠️ ПОМИЛКА ДАНИХ",
                'price': "--",
                'details': details or "Спробуйте ще раз",
                'quality': "Помилка"
            })
        
        if signal_text == "SKIP":
            return jsonify({
                'signal': "⚪️ ⚖️ НЕМАЄ ЧІТКОГО СЕТАПУ — УТРИМАТИСЬ",
                'price': details.split("|")[0].replace("Актив: ", "").split()[0] if "Актив" in details else "--",
                'details': details,
                'quality': quality
            })
        
        # Витягуємо ціну з details
        price = "--"
        if "Ціна:" in details:
            try:
                price = details.split("Ціна: ")[1].split(" ")[0]
            except:
                pass
        
        return jsonify({
            'signal': signal_text,
            'price': price,
            'details': details,
            'quality': quality
        })
        
    except Exception as e:
        return jsonify({
            'signal': "⚠️ ПОМИЛКА АНАЛІЗУ",
            'price': "--",
            'details': f"Спробуйте ще раз. ({str(e)[:50]})",
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
