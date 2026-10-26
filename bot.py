import os
import json
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import telebot
from telebot import types
from tradingview_ta import Interval, TA_Handler

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не знайдено. Створи файл .env і додай туди токен.")

bot = telebot.TeleBot(TOKEN)

# ====================== НАЛАШТУВАННЯ ======================
STATS_FILE = Path("stats.json")

ASSETS = {
    "EURUSD": {"screener": "forex", "exchange": "FX"},
    "GBPUSD": {"screener": "forex", "exchange": "FX"},
    "USDJPY": {"screener": "forex", "exchange": "FX"},
    "AUDUSD": {"screener": "forex", "exchange": "FX"},
    "USDCAD": {"screener": "forex", "exchange": "FX"},
    "USDCHF": {"screener": "forex", "exchange": "FX"},
    "NZDUSD": {"screener": "forex", "exchange": "FX"},
    "EURGBP": {"screener": "forex", "exchange": "FX"},
    "EURJPY": {"screener": "forex", "exchange": "FX"},
    "GBPJPY": {"screener": "forex", "exchange": "FX"},
    "EURAUD": {"screener": "forex", "exchange": "FX"},
    "XAUUSD": {"screener": "forex", "exchange": "OANDA"},
    "BTCUSD": {"screener": "crypto", "exchange": "BINANCE"},
    "ETHUSD": {"screener": "crypto", "exchange": "BINANCE"},
}

TIMEFRAMES = {
    "1 хвилина": {"interval": Interval.INTERVAL_1_MINUTE, "seconds": 60},
    "5 хвилин":  {"interval": Interval.INTERVAL_5_MINUTES, "seconds": 300},
    "15 хвилин": {"interval": Interval.INTERVAL_15_MINUTES, "seconds": 900},
    "30 хвилин": {"interval": Interval.INTERVAL_30_MINUTES, "seconds": 1800},
    "1 година":  {"interval": Interval.INTERVAL_1_HOUR, "seconds": 3600},
}

user_selections = {}


# ====================== РОБОТА ЗІ СТАТИСТИКОЮ ======================
def load_stats() -> dict:
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


user_stats = load_stats()


# ====================== ДОПОМІЖНІ ФУНКЦІЇ ======================
def check_news_alert() -> str:
    now = datetime.now()
    h, m = now.hour, now.minute

    if (h == 14 and m >= 30) or h in (15, 16) or (h == 17 and m <= 30):
        return (
            "⚠️ **УВАГА (НОВИННИЙ ФОН)**\n"
            "Зараз можливий вихід важливих новин (сесія США).\n"
            "Волатильність підвищена — будь обережний."
        )
    return "✅ **Новинний фон:** Спокійно. Значних ризиків немає."


def get_assets_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    keys = list(ASSETS.keys())
    for i in range(0, len(keys), 3):
        markup.add(*[types.KeyboardButton(k) for k in keys[i:i+3]])
    markup.add(types.KeyboardButton("📊 Моя статистика"))
    return markup


def get_timeframes_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    for name in TIMEFRAMES:
        markup.add(types.KeyboardButton(name))
    markup.add(types.KeyboardButton("⬅️ Назад до активів"))
    return markup


def send_statistics(chat_id: int):
    chat_id_str = str(chat_id)
    if chat_id_str not in user_stats:
        user_stats[chat_id_str] = {"wins": 0, "losses": 0}

    s = user_stats[chat_id_str]
    total = s["wins"] + s["losses"]
    winrate = (s["wins"] / total * 100) if total > 0 else 0

    text = (
        "📊 *СТАТИСТИКА УГОД*\n"
        "——————————————\n"
        f"✅ Профіт: `{s['wins']}`\n"
        f"❌ Збиток: `{s['losses']}`\n"
        f"📁 Всього угод: `{total}`\n"
        f"🎯 Вінрейт: `{winrate:.1f}%`\n"
        "——————————————"
    )
    bot.send_message(chat_id, text, parse_mode="Markdown")


# ====================== ОБРОБНИКИ ======================
@bot.message_handler(commands=["start", "menu"])
def start(message):
    bot.send_message(
        message.chat.id,
        "🐼 *PANDATRADERS PRO*\n\n"
        "Оберіть актив для глибокого технічного аналізу:",
        parse_mode="Markdown",
        reply_markup=get_assets_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text == "📊 Моя статистика")
def show_stats(message):
    send_statistics(message.chat.id)


@bot.message_handler(func=lambda m: m.text == "⬅️ Назад до активів")
def back_to_assets(message):
    bot.send_message(
        message.chat.id,
        "Оберіть актив:",
        reply_markup=get_assets_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text in ASSETS)
def choose_pair(message):
    chat_id = message.chat.id
    user_selections[chat_id] = {"pair": message.text}

    bot.send_message(
        chat_id,
        f"💎 Актив: *{message.text}*\n\nОберіть час експірації:",
        parse_mode="Markdown",
        reply_markup=get_timeframes_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text in TIMEFRAMES)
def choose_timeframe(message):
    chat_id = message.chat.id

    if chat_id not in user_selections or "pair" not in user_selections[chat_id]:
        bot.send_message(chat_id, "Спочатку оберіть актив.", reply_markup=get_assets_keyboard())
        return

    pair = user_selections[chat_id]["pair"]
    tf_name = message.text
    tf = TIMEFRAMES[tf_name]

    wait = bot.send_message(
        chat_id,
        f"🔍 Аналізую *{pair}* ({tf_name})...\nЗачекайте кілька секунд.",
        parse_mode="Markdown",
    )

    try:
        info = ASSETS[pair]
        handler = TA_Handler(
            symbol=pair,
            exchange=info["exchange"],
            screener=info["screener"],
            interval=tf["interval"],
        )
        analysis = handler.get_analysis()

        summary = analysis.summary
        ind = analysis.indicators

        rec = summary.get("RECOMMENDATION", "NEUTRAL")
        buy = summary.get("BUY", 0)
        sell = summary.get("SELL", 0)
        neutral = summary.get("NEUTRAL", 0)

        close = ind.get("close")
        rsi = ind.get("RSI")
        macd = ind.get("MACD.macd")
        macd_signal = ind.get("MACD.signal")
        ema50 = ind.get("EMA50")

        # Ціна
        if isinstance(close, (int, float)):
            price_str = f"{close:.5f}" if close < 10 else f"{close:.2f}"
        else:
            price_str = "N/A"

        # Напрямок
        if "BUY" in rec:
            direction = "⬆️ ВГОРУ (CALL)"
            emoji = "🟢"
        elif "SELL" in rec:
            direction = "⬇️ ВНИЗ (PUT)"
            emoji = "🔴"
        else:
            direction = "↔️ УТРИМАТИСЬ"
            emoji = "🟡"

        # Детальний аналіз
        lines = []

        if isinstance(rsi, (int, float)):
            if rsi < 30:
                lines.append(f"RSI у зоні перепроданості (~{rsi:.1f})")
            elif rsi > 70:
                lines.append(f"RSI у зоні перекупленості (~{rsi:.1f})")
            else:
                lines.append(f"RSI нейтральний (~{rsi:.1f})")

        if isinstance(macd, (int, float)) and isinstance(macd_signal, (int, float)):
            if macd > macd_signal:
                lines.append("MACD перетнув сигнал вгору (бичачий імпульс)")
            else:
                lines.append("MACD під сигнальною лінією (ведмежий тиск)")

        if isinstance(close, (int, float)) and isinstance(ema50, (int, float)):
            if close > ema50:
                lines.append("Ціна вище EMA50 — динамічна підтримка")
            else:
                lines.append("Ціна нижче EMA50 — динамічний опір")

        lines.append(f"Сила: BUY {buy} | SELL {sell} | NEUTRAL {neutral}")

        detailed = "\n".join(f"• {line}" for line in lines)
        news = check_news_alert()

        text = (
            f"{emoji} *ТОРГОВИЙ СИГНАЛ*\n"
            f"——————————————\n"
            f"📊 *Актив:* `{pair}`\n"
            f"💰 *Ціна входу:* `{price_str}`\n"
            f"⏱ *Таймфрейм:* `{tf_name}`\n"
            f"📈 *Напрямок:* *{direction}*\n\n"
            f"*Глибокий аналіз:*\n{detailed}\n\n"
            f"{news}\n"
            f"——————————————\n"
            f"⏳ Таймер запущено на *{tf_name}*.\n"
            f"Бот нагадає про результат."
        )

        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=wait.message_id,
            parse_mode="Markdown",
        )

        bot.send_message(
            chat_id,
            "Оберіть наступний актив або перегляньте статистику:",
            reply_markup=get_assets_keyboard(),
        )

        # Таймер зворотного зв'язку
        def ask_result():
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Профіт", callback_data=f"win_{chat_id}"),
                types.InlineKeyboardButton("❌ Збиток", callback_data=f"loss_{chat_id}"),
            )
            bot.send_message(
                chat_id,
                f"⏰ *Час угоди завершився!*\n\n"
                f"Актив: `{pair}` | {tf_name}\n"
                f"Як закрилася угода?",
                parse_mode="Markdown",
                reply_markup=markup,
            )

        threading.Timer(tf["seconds"], ask_result).start()

    except Exception as e:
        bot.edit_message_text(
            f"❌ Помилка аналізу:\n`{e}`\n\nМожливо, ринок зараз закритий.",
            chat_id=chat_id,
            message_id=wait.message_id,
            parse_mode="Markdown",
        )
        bot.send_message(chat_id, "Спробуйте інший актив:", reply_markup=get_assets_keyboard())


@bot.callback_query_handler(func=lambda c: c.data.startswith(("win_", "loss_")))
def handle_result(call):
    action, chat_id_str = call.data.split("_")
    chat_id = int(chat_id_str)
    key = str(chat_id)

    if key not in user_stats:
        user_stats[key] = {"wins": 0, "losses": 0}

    if action == "win":
        user_stats[key]["wins"] += 1
        result = "✅ Угоду зараховано як **ПРОФІТ**"
    else:
        user_stats[key]["losses"] += 1
        result = "❌ Угоду зараховано як **ЗБИТОК**"

    save_stats(user_stats)

    bot.edit_message_text(
        f"{call.message.text}\n\n{result}",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, "Результат збережено!")
    send_statistics(chat_id)


# ====================== ЗАПУСК ======================
if __name__ == "__main__":
    print("🐼 PANDATRADERS PRO бот запущено!")
    bot.infinity_polling()
