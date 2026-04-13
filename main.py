import ccxt
import telebot
from telebot import types
import pandas as pd
import pandas_ta as ta
import time
import uuid
import threading
from datetime import datetime

# --- НАСТРОЙКИ ---
TOKEN = '8548326510:AAE7lF1XAVfwtNJgEaWMiiXk7oKWr3Hq2AA'
SYMBOLS = ['BTC/USDT', 'ETH/USDT']
TIMEFRAME = '15m'  # Установлено на 15 минут 🚀
RSI_BUY_LEVEL = 30
TAKE_PROFIT_PCT = 0.02
STOP_LOSS_PCT = 0.01

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()

subscribed_users = set()
active_signals = {}
signal_history = []


# --- КЛАВИАТУРА ---
def main_menu():
    markup = types.InlineKeyboardMarkup()
    btn_history = types.InlineKeyboardButton("📖 Журнал сигналов (Last 20)", callback_data="show_history")
    markup.add(btn_history)
    return markup


# --- ЛОГИКА ПОДПИСКИ ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    subscribed_users.add(message.chat.id)
    bot.send_message(
        message.chat.id,
        "🤖 **CryptoPulse Bot [15m] запущен!**\n\nМониторю 15-минутные графики BTC и ETH. Ждите сигналов! 🔥",
        parse_mode='Markdown',
        reply_markup=main_menu()
    )


@bot.callback_query_handler(func=lambda call: call.data == "show_history")
def callback_history(call):
    if not signal_history:
        text = "📭 Журнал пуст. На 15м графике сигналы скоро появятся!"
    else:
        text = "📜 **ЖУРНАЛ СОБЫТИЙ (15m):**\n\n"
        for item in signal_history[-20:]:
            text += f"{item}\n"

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=main_menu())


def broadcast(text):
    for user_id in list(subscribed_users):
        try:
            bot.send_message(user_id, text, parse_mode='Markdown')
        except:
            pass


# --- АНАЛИЗ РЫНКА ---
def check_market():
    for symbol in SYMBOLS:
        try:
            # Запрашиваем свечи 15m
            bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['rsi'] = ta.rsi(df['close'], length=14)
            last_price = df['close'].iloc[-1]
            last_rsi = df['rsi'].iloc[-1]

            check_closures(symbol, last_price)

            already_in_trade = any(s['symbol'] == symbol for s in active_signals.values())
            if last_rsi <= RSI_BUY_LEVEL and not already_in_trade:
                create_signal(symbol, last_price, last_rsi)
        except Exception as e:
            print(f"Ошибка биржи: {e}")


def create_signal(symbol, price, rsi):
    sid = str(uuid.uuid4())[:8]
    tp = price * (1 + TAKE_PROFIT_PCT)
    sl = price * (1 - STOP_LOSS_PCT)
    start_time = datetime.now().strftime("%H:%M")

    active_signals[sid] = {
        'symbol': symbol,
        'price': price,
        'tp': tp,
        'sl': sl,
        'start_time': start_time
    }

    msg = (
        f"⚡️ **НОВЫЙ СИГНАЛ [#{sid}]**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Пара:** {symbol}\n"
        f"📥 **Вход:** {price}\n"
        f"📊 **RSI (15m):** {rsi:.2f}\n"
        f"🕒 **Открыт:** {start_time}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **TP:** {tp:.2f} (+2%)\n"
        f"🛑 **SL:** {sl:.2f} (-1%)\n"
    )
    broadcast(msg)


def check_closures(symbol, current_price):
    to_delete = []
    end_time = datetime.now().strftime("%H:%M")

    for sid, data in active_signals.items():
        if data['symbol'] == symbol:
            result_entry = ""
            if current_price >= data['tp']:
                result_entry = f"✅ `#{sid}` {symbol}\n└ 💰 **+2.0%** ({data['start_time']} → {end_time})\n"
                broadcast(f"🟢 **ПРИБЫЛЬ [#{sid}]**\n💰 {symbol} дошел до цели! ({end_time})")
                to_delete.append(sid)
            elif current_price <= data['sl']:
                result_entry = f"❌ `#{sid}` {symbol}\n└ 📉 **-1.0%** ({data['start_time']} → {end_time})\n"
                broadcast(f"🔴 **СТОП-ЛОСС [#{sid}]**\n📉 {symbol} закрыт по стопу ({end_time})")
                to_delete.append(sid)

            if result_entry:
                signal_history.append(result_entry)
                if len(signal_history) > 20: signal_history.pop(0)

    for sid in to_delete:
        del active_signals[sid]


if __name__ == "__main__":
    print("Бот запущен на 15-минутном таймфрейме...")
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    while True:
        if subscribed_users:
            check_market()
        time.sleep(60)