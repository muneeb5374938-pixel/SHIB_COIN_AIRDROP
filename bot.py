import os
import http.server
import socketserver
import threading
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# --- LOAD ENVIRONMENT VARIABLES ---
load_dotenv() # This loads the .env file if you are testing on your computer

# Line 12: We grab the BOT_TOKEN from your .env file or Railway variables
TOKEN = os.getenv("BOT_TOKEN") 

# Line 15: We grab the WEBAPP_URL from your .env file or Railway variables
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8080")


# --- WEB SERVER FOR RAILWAY ---
# This small server runs in the background to serve your index.html file
class WebAppHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            with open("index.html", "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "File not found")

def run_server():
    # Railway assigns a PORT automatically. We use 8080 as a fallback.
    port = int(os.getenv("PORT", "8080"))
    with socketserver.TCPServer(("", port), WebAppHandler) as httpd:
        print(f"Web server running on port {port}")
        httpd.serve_forever()


# --- BOT COMMANDS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command and sends the Web App button."""
    
    # The message sent to the user
    welcome_text = (
        "👋 **Welcome to the SHIB OFFICIAL AIRDROP ROBOT!**\n\n"
        "Click the button below to open the Web App."
    )
    
    # Line 51: This is where the WEBAPP_URL is injected into the button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Open Web App", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    await update.message.reply_text(
        text=welcome_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# --- MAIN BOT LAUNCHER ---
def main():
    # 1. Start the web server in the background
    threading.Thread(target=run_server, daemon=True).start()
    
    # 2. Build and start the bot
    if not TOKEN:
        print("ERROR: BOT_TOKEN is missing. Please add it to your .env file.")
        return

    app = Application.builder().token(TOKEN).build()
    
    # Register the /start command
    app.add_handler(CommandHandler("start", start_command))
    
    print("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
  
