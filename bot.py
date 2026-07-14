import os
import sqlite3
import http.server
import socketserver
import threading
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# --- SETUP LOGGING ---
# This will print exact errors in your Railway logs if anything goes wrong
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- LOAD CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

# Safeguard: Telegram crashes if WebApp URL doesn't start with https://
if not WEBAPP_URL.startswith("https://"):
    WEBAPP_URL = "https://google.com" # Fallback to prevent crash

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("airdrop.db", check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0, referred_by INTEGER, invites INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_link TEXT, channel_id TEXT, prize INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS withdraws 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, pay_id TEXT, amount INTEGER, status TEXT DEFAULT 'pending')''')
    conn.commit()
    conn.close()

init_db()

# --- WEB SERVER FOR RAILWAY & TELEGRAM WEB APP ---
class WebAppHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            try:
                with open("index.html", "rb") as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                self.wfile.write(b"index.html not found.")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot Server Alive")

def run_server():
    port = int(os.getenv("PORT", "8080"))
    # allow_reuse_address prevents "Address already in use" crashes on Railway
    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        
    with ThreadedTCPServer(("0.0.0.0", port), WebAppHandler) as httpd:
        logger.info(f"Web server running on port {port}")
        httpd.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# --- KEYBOARDS ---
def main_menu():
    keyboard = [['1st_Home', '2nd_Tasks'], ['3rd_Withdraw', '4rth_Profile']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- BOT COMMANDS & HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        args = context.args
        
        conn = sqlite3.connect("airdrop.db", check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id=?", (user.id,))
        existing_user = c.fetchone()
        
        referred_by = None
        if not existing_user:
            if args and args[0].isdigit() and int(args[0]) != user.id:
                referred_by = int(args[0])
                c.execute("UPDATE users SET balance = balance + 1000, invites = invites + 1 WHERE user_id=?", (referred_by,))
            
            c.execute("INSERT INTO users (user_id, username, balance, referred_by) VALUES (?, ?, ?, ?)", 
                      (user.id, user.username, 0, referred_by))
            conn.commit()
        conn.close()

        welcome_text = (
            "🚀 **WELCOME TO THE SHIB OFFICIAL AIRDROP ROBOT** 🚀\n\n"
            "Earn free $SHIB tokens by completing simple tasks, watching high-paying ads, and inviting your friends!\n\n"
            "🎁 *Instant registration bonus active!*\n"
            "👥 *Earn 1,000 SHIB per successful referral!*"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=main_menu())
    except Exception as e:
        logger.error(f"Error in /start: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        user_id = update.effective_user.id
        
        conn = sqlite3.connect("airdrop.db", check_same_thread=False)
        c = conn.cursor()
        
        if text == '1st_Home':
            c.execute("SELECT username, invites FROM users ORDER BY invites DESC LIMIT 10")
            leaders = c.fetchall()
            leaderboard = "🏆 **TOP 10 REFERRERS LEADERBOARD** 🏆\n\n"
            for idx, l in enumerate(leaders, 1):
                name = l[0] if l[0] else "Anonymous"
                leaderboard += f"{idx}. @{name} — {l[1]} Invites\n"
            
            inline_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📺 Watch Ad (500 SHIB)", web_app=WebAppInfo(url=WEBAPP_URL))]
            ])
            await update.message.reply_text(f"{leaderboard}\n⚡ *Click below to open the Web App, watch an ad, and earn:*", 
                                           parse_mode="Markdown", reply_markup=inline_kb)
            
        elif text == '2nd_Tasks':
            c.execute("SELECT id, channel_link, prize FROM tasks")
            all_tasks = c.fetchall()
            if not all_tasks:
                await update.message.reply_text("❌ No promotional tasks available right now.")
            else:
                await update.message.reply_text("📋 **AVAILABLE TASKS**\n\nJoin the channels below and press Verify:")
                for t in all_tasks:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Join Channel", url=t[1])],
                        [InlineKeyboardButton("✅ Verify", callback_data=f"verify_{t[0]}")]
                    ])
                    await update.message.reply_text(f"🎁 Reward: {t[2]} SHIB", reply_markup=kb)

        elif text == '3rd_Withdraw':
            c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            balance = c.fetchone()[0]
            if balance < 5000:
                await update.message.reply_text("❌ Minimum withdrawal amount is **5,000 SHIB**.")
            else:
                context.user_data['awaiting_pay_id'] = True
                await update.message.reply_text("💳 Please enter your **Binance Pay ID** to request withdrawal:")

        elif text == '4rth_Profile':
            c.execute("SELECT balance, invites FROM users WHERE user_id=?", (user_id,))
            res = c.fetchone()
            bot_info = await context.bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
            profile_msg = (
                f"👤 **YOUR PROFILE**\n\n"
                f"💰 Balance: `{res[0]}` SHIB\n"
                f"👥 Total Invites: `{res[1]}` users\n\n"
                f"🔗 *Your Unique Referral Link:*\n{ref_link}"
            )
            await update.message.reply_text(profile_msg, parse_mode="Markdown")
            
        elif context.user_data.get('awaiting_pay_id'):
            pay_id = text
            context.user_data['awaiting_pay_id'] = False
            c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            balance = c.fetchone()[0]
            
            c.execute("INSERT INTO withdraws (user_id, pay_id, amount) VALUES (?, ?, ?)", (user_id, pay_id, balance))
            c.execute("UPDATE users SET balance = 0 WHERE user_id=?", (user_id,))
            conn.commit()
            await update.message.reply_text("✅ Withdrawal request submitted! It will appear in the Admin Panel shortly.")
            
        conn.close()
    except Exception as e:
        logger.error(f"Error handling message: {e}")

async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.effective_message.web_app_data.data
    user_id = update.effective_user.id
    if data == "ad_completed":
        conn = sqlite3.connect("airdrop.db", check_same_thread=False)
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + 500 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text("🎉 Good job! You watched the ad and earned **500 SHIB**!")

async def verify_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    
    conn = sqlite3.connect("airdrop.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT channel_id, prize FROM tasks WHERE id=?", (task_id,))
    task = c.fetchone()
    
    if task:
        try:
            member = await context.bot.get_chat_member(chat_id=task[0], user_id=user_id)
            if member.status in ['member', 'administrator', 'creator']:
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (task[1], user_id))
                conn.commit()
                await query.edit_message_text("✅ Verified! Reward added successfully.")
            else:
                await context.bot.send_message(chat_id=user_id, text="❌ Verification failed! Please join the channel first.")
        except Exception as e:
            logger.error(f"Verification error: {e}")
            await context.bot.send_message(chat_id=user_id, text="⚠️ Error checking status. Make sure the bot is an Admin inside the targeted channel.")
    conn.close()

# --- ADMIN ROUTINES ---
async def add_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        link = context.args[0]
        channel_id = context.args[1]
        prize = int(context.args[2])
        
        conn = sqlite3.connect("airdrop.db", check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO tasks (channel_link, channel_id, prize) VALUES (?, ?, ?)", (link, channel_id, prize))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ New Task Added Successfully!")
    except Exception:
        await update.message.reply_text("⚠️ Syntax: `/Task [Link] [ID] [Prize]`\nExample: `/Task t.me/mychannel -1001234567 2000`")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1. All", callback_data="adm_all"), InlineKeyboardButton("2. Pending", callback_data="adm_pending")],
        [InlineKeyboardButton("3. Paying", callback_data="adm_paying"), InlineKeyboardButton("4. Paid", callback_data="adm_paid")]
    ])
    await update.message.reply_text("🛠️ **ADMIN CONTROL DASHBOARD**", reply_markup=kb)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return
    await query.answer()
    
    action = query.data.split("_")[1]
    conn = sqlite3.connect("airdrop.db", check_same_thread=False)
    c = conn.cursor()
    
    if action == "all":
        c.execute("SELECT * FROM withdraws")
    else:
        c.execute("SELECT * FROM withdraws WHERE status=?", (action,))
        
    records = c.fetchall()
    if not records:
        await query.edit_message_text(f"No records found for: '{action.upper()}'.")
        conn.close()
        return
        
    await query.message.reply_text(f"📊 Results for {action.upper()}:")
    for r in records:
        kb = None
        if r[4] != 'paid':
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Mark as Paying", callback_data=f"set_paying_{r[0]}")],
                [InlineKeyboardButton("Mark as Paid ✅", callback_data=f"set_paid_{r[0]}")]
            ])
        await query.message.reply_text(f"🆔 ID: {r[0]}\n👤 User ID: {r[1]}\n💳 Pay ID: `{r[2]}`\n💰 Amount: {r[3]} SHIB\n📌 Status: {r[4].upper()}", reply_markup=kb)
    conn.close()

async def update_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return
    await query.answer()
    
    _, target_status, record_id = query.data.split("_")
    conn = sqlite3.connect("airdrop.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE withdraws SET status=? WHERE id=?", (target_status, record_id))
    
    if target_status == "paid":
        c.execute("SELECT user_id, amount FROM withdraws WHERE id=?", (record_id,))
        user_id, amount = c.fetchone()
        try:
            await context.bot.send_message(chat_id=user_id, text=f"🎉 **Your withdrawal of {amount} SHIB has been processed and marked as PAID!**")
        except Exception as e:
            logger.error(f"Failed to message user on paid status: {e}")
            
    conn.commit()
    conn.close()
    await query.edit_message_text(f"✅ Record #{record_id} changed to {target_status.upper()}")

def main():
    if not TOKEN:
        logger.error("Missing BOT_TOKEN variable! Please set it in Railway Variables.")
        return

    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("Task", add_task_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(verify_task, pattern="^verify_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(update_status_callback, pattern="^set_"))
    
    logger.info("Bot is successfully running...")
    app.run_polling()

if __name__ == '__main__':
    main()
            
