import logging
import ccxt
import telebot
from telebot import types
import pandas as pd
import time
import os
import json
import threading
import uuid
from datetime import datetime

# --- КОНФИГУРАЦИЯ ---
TOKEN = '8548326510:AAGWO3mrvE_ZCbO4jHKs2TkPM_Agn51v7PE'
SYMBOLS = ['BTC/USDT', 'ETH/USDT']
TP_PERCENT = 1.5  # Тейк-профит 1.5%
SL_PERCENT = 1.0  # Стоп-лосс 1.0%

# Файлы базы данных
HISTORY_FILE = 'trade_history.json'
ACTIVE_FILE = 'active_trades.json'

# Глобальные переменные
MY_CHAT_ID = None
active_trades = []
signal_history = []
last_sent_signals = {symbol: None for symbol in SYMBOLS}

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()

# --- РАБОТА С ДАННЫМИ ---
def load_data():
    global active_trades, signal_history
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                signal_history = json.load(f)
        if os.path.exists(ACTIVE_FILE):
            with open(ACTIVE_FILE, 'r') as f:
                active_trades = json.load(f)
        print(f"✅ Данные загружены. Сделок в истории: {len(signal_history)}")
    except Exception as e:
        print(f"❌ Ошибка загрузки данных: {e}")

def save_data():
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(signal_history, f, indent=4)
        with open(ACTIVE_FILE, 'w') as f:
            json.dump(active_trades, f, indent=4)
    except Exception as e:
        print(f"❌ Ошибка сохранения данных: {e}")

# --- ТЕХНИЧЕСКИЙ АНАЛИЗ ---
def get_rsi(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    except:
        return 50

# --- СКАНЕР И МОНИТОРИНГ ---
def scanner():
    global active_trades, signal_history, MY_CHAT_ID, last_sent_signals
    print("🚀 Сканер запущен и ищет сигналы...")
    
    while True:
        try:
            if MY_CHAT_ID:
                # 1. Поиск новых сигналов
                for symbol in SYMBOLS:
                    rsi = get_rsi(symbol)
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker['last']
                    
                    side = None
                    if rsi <= 30 and last_sent_signals[symbol] != "BUY":
                        side = "BUY 🟢"
                        tp = price * (1 + TP_PERCENT/100)
                        sl = price * (1 - SL_PERCENT/100)
                    elif rsi >= 70 and last_sent_signals[symbol] != "SELL":
                        side = "SELL 🔴"
                        tp = price * (1 - TP_PERCENT/100)
                        sl = price * (1 + SL_PERCENT/100)

                    if side:
                        new_trade = {
                            "id": str(uuid.uuid4())[:8],
                            "symbol": symbol,
                            "side": side,
                            "entry_price": price,
                            "tp": round(tp, 2),
                            "sl": round(sl, 2),
                            "time_in": datetime.now().strftime("%H:%M:%S"),
                            "status": "OPEN"
                        }
                        active_trades.append(new_trade)
                        last_sent_signals[symbol] = "BUY" if "BUY" in side else "SELL"
                        save_data()
                        
                        msg = (f"🚀 **ВХОД В СДЕЛКУ: {symbol}**\n"
                               f"Направление: {side}\n"
                               f"Цена входа: `{price}`\n"
                               f"🎯 TP: `{round(tp, 2)}` | 🛡️ SL: `{round(sl, 2)}`\n"
                               f"📊 RSI: {round(rsi, 2)}")
                        bot.send_message(MY_CHAT_ID, msg, parse_mode="Markdown")

                    # Сброс флага сигнала, если RSI вернулся в нейтральную зону
                    if 35 < rsi < 65:
                        last_sent_signals[symbol] = None

                # 2. Проверка закрытия активных сделок
                for trade in active_trades[:]:
                    ticker = exchange.fetch_ticker(trade['symbol'])
                    curr_price = ticker['last']
                    
                    is_closed = False
                    res_emoji = ""

                    if "BUY" in trade['side']:
                        if curr_price >= trade['tp']:
                            is_closed, res_emoji = True, "✅ TAKE PROFIT"
                        elif curr_price <= trade['sl']:
                            is_closed, res_emoji = True, "❌ STOP LOSS"
                    else: # SELL
                        if curr_price <= trade['tp']:
                            is_closed, res_emoji = True, "✅ TAKE PROFIT"
                        elif curr_price >= trade['sl']:
                            is_closed, res_emoji = True, "❌ STOP LOSS"

                    if is_closed:
                        trade['status'] = "CLOSED"
                        trade['exit_price'] = curr_price
                        trade['result'] = res_emoji
                        trade['time_out'] = datetime.now().strftime("%H:%M:%S")
                        
                        signal_history.append(trade)
                        active_trades.remove(trade)
                        save_data()
                        
                        msg = (f"🏁 **СДЕЛКА ЗАКРЫТА: {trade['symbol']}**\n"
                               f"Итог: {res_emoji}\n"
                               f"Цена выхода: `{curr_price}`\n"
                               f"Вход был в: {trade['time_in']}")
                        bot.send_message(MY_CHAT_ID, msg, parse_mode="Markdown")

            time.sleep(20) # Пауза между проверками
        except Exception as e:
            print(f"⚠️ Ошибка сканера: {e}")
            time.sleep(10)

# --- ОБРАБОТЧИКИ ТЕЛЕГРАМ ---
@bot.message_handler(commands=['start'])
def start(message):
    global MY_CHAT_ID
    MY_CHAT_ID = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📊 Показать Журнал"), types.KeyboardButton("📡 Активные сделки"))
    
    bot.send_message(
        MY_CHAT_ID, 
        "🤖 Бот-трейдер запущен!\nЯ слежу за RSI на 15m и сопровождаю сделки до TP/SL.",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == "📊 Показать Журнал")
def show_history(message):
    if not signal_history:
        bot.send_message(message.chat.id, "📭 Журнал пуст.")
        return
    
    text = "📜 **ПОСЛЕДНИЕ РЕЗУЛЬТАТЫ:**\n\n"
    for t in signal_history[-10:]:
        text += f"• {t['symbol']} | {t['time_in']} | {t['result']} (`{t['exit_price']}`)\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "📡 Активные сделки")
def show_active(message):
    if not active_trades:
        bot.send_message(message.chat.id, "⏸ Сейчас нет открытых позиций.")
        return
    
    text = "📡 **В ПРОЦЕССЕ:**\n\n"
    for t in active_trades:
        text += f"• {t['symbol']} {t['side']}\nВход: `{t['entry_price']}` | Цель: `{t['tp']}`\n\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# --- ЗАПУСК ---
if __name__ == "__main__":
    load_data()
    threading.Thread(target=scanner, daemon=True).start()
    print("🚀 Бот запущен. Ожидание команды /start в Telegram...")
    bot.polling(none_stop=True)
