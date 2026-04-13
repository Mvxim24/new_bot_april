import sys
import logging
import ccxt
import telebot
from telebot import types
import pandas as pd
import time
import uuid
import threading
import json
import os
from datetime import datetime

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- КОНФИГУРАЦИЯ ---
TOKEN = '8548326510:AAE7lF1XAVfwtNJgEaWMiiXk7oKWr3Hq2AA'
SYMBOLS = ['BTC/USDT', 'ETH/USDT']

HISTORY_FILE = 'trade_history.json'
ACTIVE_FILE = 'active_trades.json'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()

active_trades = []
signal_history = []


# --- БАЗА ДАННЫХ ---
def load_data():
    global active_trades, signal_history
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                signal_history = json.load(f)
        if os.path.exists(ACTIVE_FILE):
            with open(ACTIVE_FILE, 'r') as f:
                active_trades = json.load(f)
        print(f"--- ДАННЫЕ ЗАГРУЖЕНЫ (История: {len(signal_history)}) ---")
    except Exception as e:
        print(f"Ошибка загрузки: {e}")


def save_data():
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(signal_history, f, indent=4)
        with open(ACTIVE_FILE, 'w') as f:
            json.dump(active_trades, f, indent=4)
    except Exception as e:
        print(f"Ошибка сохранения: {e}")


# --- МОНИТОРИНГ РЫНКА (RSI) ---
def get_rsi(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs)).iloc[-1]
    except:
        return 50


def scanner():
    while True:
        try:
            for symbol in SYMBOLS:
                rsi = get_rsi(symbol)
                # Здесь логика открытия/закрытия сделок
                pass
            time.sleep(30)
        except Exception as e:
            print(f"Ошибка сканера: {e}")
            time.sleep(10)


# --- ГЛАВНОЕ МЕНЮ (КЛАВИАТУРА) ---
def get_main_menu():
    # Используем обычные кнопки вместо Inline
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_history = types.KeyboardButton("📊 Показать Журнал")
    markup.add(btn_history)
    return markup


# --- ОБРАБОТЧИКИ КОМАНД ---

@bot.message_handler(commands=['start'])
def start(message):
    print(f"Пользователь {message.chat.id} нажал /start")
    bot.send_message(
        message.chat.id,
        "🤖 Бот-аналитик запущен!\n\nИспользуй кнопку внизу для просмотра журнала.",
        reply_markup=get_main_menu()
    )


@bot.message_handler(func=lambda message: message.text == "📊 Показать Журнал")
def show_history(message):
    print(f"--- ЗАПРОС ЖУРНАЛА ОТ {message.chat.id} ---")

    if not signal_history:
        text = "📭 Журнал пока пуст.\nЗакрытых сделок не найдено."
    else:
        text = "📜 ПОСЛЕДНИЕ СДЕЛКИ:\n\n"
        for t in signal_history[-10:]:
            text += f"• {t.get('symbol')} | {t.get('direction')} | {t.get('status')}\n"

    bot.send_message(message.chat.id, text)
    print("--- ОТВЕТ ОТПРАВЛЕН ---")


# --- ЗАПУСК ---
if __name__ == "__main__":
    load_data()

    # Поток для проверки биржи
    threading.Thread(target=scanner, daemon=True).start()

    print("🚀 Бот активен. Напиши /start в Telegram.")

    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"Ошибка сети: {e}")
            time.sleep(5)
