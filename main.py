import asyncio
import aiosqlite
import time
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from binance import AsyncClient, BinanceSocketManager

# --- НАСТРОЙКИ ---
API_TOKEN = '8548326510:AAEQxJf_59QWFcNOXpFKxKRowq69tbfCwao'
IMBALANCE_COEFF = 2.5
COOLDOWN_TIME = 1800 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
last_signals = {"BTCUSDT": 0, "ETHUSDT": 0}

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect('trades.db') as db:
        # Таблица журнала сделок
        await db.execute('''CREATE TABLE IF NOT EXISTS journal 
            (id INTEGER PRIMARY KEY, pair TEXT, side TEXT, price REAL, 
             sl REAL, tp REAL, status TEXT, time TEXT)''')
        # Таблица подписчиков
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY)''')
        await db.commit()

async def add_user(user_id):
    async with aiosqlite.connect('trades.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect('trades.db') as db:
        cursor = await db.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def add_to_journal(pair, side, price, sl, tp):
    async with aiosqlite.connect('trades.db') as db:
        t = time.strftime('%H:%M:%S')
        await db.execute("INSERT INTO journal (pair, side, price, sl, tp, status, time) VALUES (?,?,?,?,?,?,?)",
                         (pair, side, price, sl, tp, "OPEN", t))
        await db.commit()

# --- ЛОГИКА ТРЕЙДИНГА ---
async def monitor_market():
    client = await AsyncClient.create()
    bm = BinanceSocketManager(client)
    ms = bm.multiplex_socket(['btcusdt@depth20', 'ethusdt@depth20', 'btcusdt@ticker', 'ethusdt@ticker'])

    async with ms as stream:
        while True:
            res = await stream.recv()
            data = res['data']
            symbol = res['stream'].split('@')[0].upper()

            if 'depth' in res['stream']:
                bids_vol = sum(float(i[1]) for i in data['bids'])
                asks_vol = sum(float(i[1]) for i in data['asks'])
                curr_price = float(data['bids'][0][0])
                
                if time.time() - last_signals.get(symbol, 0) > COOLDOWN_TIME:
                    side = None
                    if bids_vol > asks_vol * IMBALANCE_COEFF: side = "LONG"
                    elif asks_vol > bids_vol * IMBALANCE_COEFF: side = "SHORT"
                    
                    if side:
                        last_signals[symbol] = time.time()
                        tp = curr_price * 1.02 if side == "LONG" else curr_price * 0.98
                        sl = curr_price * 0.99 if side == "LONG" else curr_price * 1.01
                        await add_to_journal(symbol, side, curr_price, sl, tp)
                        await broadcast_signal(symbol, side, curr_price, sl, tp)

            elif 'ticker' in res['stream']:
                price = float(data['c'])
                await check_trade_close(symbol, price)

async def check_trade_close(pair, current_price):
    async with aiosqlite.connect('trades.db') as db:
        cursor = await db.execute("SELECT id, side, sl, tp FROM journal WHERE pair=? AND status='OPEN'", (pair,))
        trades = await cursor.fetchall()
        for t_id, side, sl, tp in trades:
            status = None
            if side == "LONG":
                if current_price >= tp: status = "✅ TP"
                elif current_price <= sl: status = "❌ SL"
            else:
                if current_price <= tp: status = "✅ TP"
                elif current_price >= sl: status = "❌ SL"
            
            if status:
                await db.execute("UPDATE journal SET status=? WHERE id=?", (status, t_id))
                await db.commit()
                users = await get_all_users()
                for user_id in users:
                    try:
                        await bot.send_message(user_id, f"🔔 Сделка #{t_id} ({pair}) закрыта: {status}")
                    except: continue

async def broadcast_signal(pair, side, price, sl, tp):
    text = (f"🔥 **SIGNAL: #{pair}**\n\n"
            f"**Направление:** {side} {'📈' if side=='LONG' else '📉'}\n"
            f"**Вход:** `{price:.2f}`\n"
            f"🎯 **TP (2%):** `{tp:.2f}`\n"
            f"⛔ **SL (1%):** `{sl:.2f}`")
    
    users = await get_all_users()
    for user_id in users:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка отправки пользователю {user_id}: {e}")

# --- ИНТЕРФЕЙС БОТА ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await add_user(message.from_user.id)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📊 Журнал")]], resize_keyboard=True)
    await message.answer("Вы подписаны на сигналы BTC/ETH! Ожидайте идеальный вход...", reply_markup=kb)

@dp.message(F.text == "📊 Журнал")
async def show_journal(message: types.Message):
    async with aiosqlite.connect('trades.db') as db:
        cursor = await db.execute("SELECT pair, side, status, time FROM journal ORDER BY id DESC LIMIT 10")
        rows = await cursor.fetchall()
        if not rows:
            return await message.answer("Журнал пуст.")
        
        report = "📋 **Последние сигналы:**\n\n"
        for p, s, st, t in rows:
            report += f"🕒 {t} | {p} | {s} | {st}\n"
        await message.answer(report, parse_mode="Markdown")

async def main():
    await init_db()
    # Запускаем мониторинг рынка в фоне
    asyncio.create_task(monitor_market())
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
