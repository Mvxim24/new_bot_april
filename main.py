import sys
import logging
import ccxt
import telebot
from telebot import types
import pandas as pd
import time
import uuid
import threading
from datetime import datetime, timedelta

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

print("=== ЗАПУСК ТОРГОВОГО АВТОПИЛОТА ===")

# --- КОНФИГУРАЦИЯ ---
TOKEN = '8548326510:AAE7lF1XAVfwtNJgEaWMiiXk7oKWr3Hq2AA'
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
TIMEFRAME = '15m'

# Параметры стратегии
RSI_PERIOD = 14
RSI_OVERSOLD = 30  # Для Long
RSI_OVERBOUGHT = 70  # Для Short

# Риск-менеджмент
TP_PERCENT = 0.03  # 3% Тейк-профит
SL_PERCENT = 0.015  # 1.5% Стоп-лосс

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()

# Хранилище данных
subscribed_users = set()
active_trades = []  # Список открытых виртуальных сделок
signal_history = []  # Список закрытых сделок
last_check_time = {}  # Для предотвращения спама сигналами


# --- МАТЕМАТИКА ---

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(span=period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


# --- ИНТЕРФЕЙС ---

def main_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📊 Показать Журнал", callback_data="show_history"))
    return markup


# --- ЛОГИКА МОНИТОРИНГА ---

def check_market():
    global active_trades, signal_history
    logging.info(f">>> Сканирование {len(SYMBOLS)} пар. Активных сделок: {len(active_trades)}")

    for symbol in SYMBOLS:
        try:
            # Получаем данные
            bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
            df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            df['rsi'] = calculate_rsi(df['close'], RSI_PERIOD)

            last_price = df['close'].iloc[-1]
            last_rsi = df['rsi'].iloc[-1]
            prev_rsi = df['rsi'].iloc[-2]

            now = datetime.now()

            # 1. ПРОВЕРКА ОТКРЫТЫХ СДЕЛК (Виртуальный трекинг)
            for trade in active_trades[:]:
                if trade['symbol'] == symbol:
                    is_closed = False
                    result_status = ""

                    if trade['direction'] == 'LONG':
                        if last_price >= trade['tp']:
                            result_status = "✅ TP"
                            is_closed = True
                        elif last_price <= trade['sl']:
                            result_status = "❌ SL"
                            is_closed = True

                    elif trade['direction'] == 'SHORT':
                        if last_price <= trade['tp']:
                            result_status = "✅ TP"
                            is_closed = True
                        elif last_price >= trade['sl']:
                            result_status = "❌ SL"
                            is_closed = True

                    if is_closed:
                        trade['status'] = result_status
                        trade['close_price'] = last_price
                        signal_history.append(trade)
                        active_trades.remove(trade)
                        broadcast(f"🔔 **Сделка #{trade['id']} ({trade['symbol']}) закрыта по {result_status}**")

            # 2. ПОИСК НОВЫХ СИГНАЛОВ
            # Проверяем, нет ли уже открытой сделки по этому символу
            is_already_open = any(t['symbol'] == symbol for t in active_trades)

            if not is_already_open:
                direction = None

                # Условие для LONG (Перепроданность + разворот вверх)
                if last_rsi < RSI_OVERSOLD and last_rsi > prev_rsi:
                    direction = 'LONG'
                    tp = last_price * (1 + TP_PERCENT)
                    sl = last_price * (1 - SL_PERCENT)

                # Условие для SHORT (Перегретость + разворот вниз)
                elif last_rsi > RSI_OVERBOUGHT and last_rsi < prev_rsi:
                    direction = 'SHORT'
                    tp = last_price * (1 - TP_PERCENT)
                    sl = last_price * (1 + SL_PERCENT)

                if direction:
                    sig_id = str(uuid.uuid4())[:6].upper()
                    new_trade = {
                        'id': sig_id,
                        'symbol': symbol,
                        'direction': direction,
                        'entry': last_price,
                        'tp': tp,
                        'sl': sl,
                        'time': now.strftime('%H:%M'),
                        'status': 'OPEN'
                    }
                    active_trades.append(new_trade)
                    send_signal_card(new_trade)

        except Exception as e:
            logging.error(f"Ошибка при анализе {symbol}: {e}")


# --- ОТПРАВКА СООБЩЕНИЙ ---

def send_signal_card(t):
    emoji = "🟢" if t['direction'] == 'LONG' else "🔴"
    text = (
        f"{emoji} **НОВЫЙ СИГНАЛ: {t['symbol']}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{t['id']}`\n"
        f"📈 Направление: **{t['direction']}**\n"
        f"💰 Вход: `{t['entry']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Take Profit (3%): `{t['tp']:.2f}`\n"
        f"🛑 Stop Loss (1.5%): `{t['sl']:.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    broadcast(text)


def broadcast(text):
    for user_id in list(subscribed_users):
        try:
            bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_menu())
        except Exception as e:
            logging.error(f"Ошибка отправки пользователю {user_id}: {e}")


# --- ОБРАБОТЧИКИ ТЕЛЕГРАМ ---

@bot.message_handler(commands=['start'])
def start_cmd(message):
    subscribed_users.add(message.chat.id)
    bot.send_message(
        message.chat.id,
        "🚀 **Бот-аналитик активирован!**\n\nЯ отслеживаю Long и Short сигналы. Когда сделка закроется, я пришлю уведомление.",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


@bot.callback_query_handler(func=lambda call: call.data == "show_history")
def history_callback(call):
    try:
        bot.answer_callback_query(call.id)
        if not signal_history:
            msg = "📭 **Журнал пуст.**\nАктивных или закрытых сделок пока нет."
        else:
            # Показываем последние 10 закрытых сделок
            lines = []
            for t in signal_history[-10:]:
                lines.append(f"`#{t['id']}` | {t['symbol']} | {t['direction']} | {t['status']}")
            msg = "📜 **ЖУРНАЛ ПОСЛЕДНИХ СДЕЛОК:**\n\n" + "\n".join(lines)

        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown", reply_markup=main_menu())
    except Exception as e:
        logging.error(f"Ошибка истории: {e}")


# --- ЦИКЛ РАБОТЫ ---

def monitoring_loop():
    while True:
        check_market()
        time.sleep(30)  # Проверка каждые 30 секунд


if __name__ == "__main__":
    # Запуск потока мониторинга рынка
    threading.Thread(target=monitoring_loop, daemon=True).start()

    # Запуск бота
    logging.info("Telegram Bot запущен...")
    bot.infinity_polling()