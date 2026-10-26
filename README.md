# 🐼 PANDATRADERS PRO

Telegram-бот для технічного аналізу валютних пар, золота та криптовалют.

## Можливості

- Глибокий технічний аналіз (RSI + MACD + EMA50)
- 14 активів (форекс + XAUUSD + BTC/ETH)
- 5 таймфреймів (1м, 5м, 15м, 30м, 1г)
- Перевірка новинного фону (сесія США)
- Автоматичний таймер угоди
- Статистика профіт/збиток + вінрейт (зберігається в `stats.json`)

## Встановлення

```bash
git clone https://github.com/ТВІЙ_НІК/pandatraders-bot.git
cd pandatraders-bot

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Створи файл `.env` на основі прикладу:

```bash
cp .env.example .env
```

Відкрий `.env` і встав свій токен від [@BotFather](https://t.me/BotFather):

```env
8936172597:AAEywuty5IyPD4yW5jdfPS9rQddOcBrKFaoBOT_TOKEN=твій_токен_тут
```

Запуск:

```bash
python bot.py
```

## Використання

1. Надішли боту `/start`
2. Обери актив
3. Обери таймфрейм
4. Отримай сигнал + глибокий аналіз
5. Після закінчення таймера вкажи результат угоди (Профіт / Збиток)

## Важливо

- Файл `.env` і `stats.json` **не** потрібно заливати на GitHub (вони вже в `.gitignore`)
- Токен бери тільки в [@BotFather](https://t.me/BotFather)
- Бот використовує бібліотеку `tradingview-ta` для отримання даних з TradingView

## Ліцензія

MIT
