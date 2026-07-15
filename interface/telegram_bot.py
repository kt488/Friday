import os
import sys
import logging
import time
import re

# Add project root to sys.path so 'core' and other modules are found
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler
from telegram.request import HTTPXRequest
from core.friday import FridayCore
from core.config import Config

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Initialize Friday Core
friday = FridayCore()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="I'm here. System is fully integrated and awaiting your command. What's on your mind?"
    )

async def process_and_respond(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text=None, image_path=None):
    chat_id = update.effective_chat.id
    
    # Send a "typing" action
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Initialize placeholder message
    if image_path:
        placeholder = "Analyzing image..."
    elif user_text and "[FILE:" in user_text:
        placeholder = "Parsing file..."
    else:
        placeholder = "..."
    status_msg = await context.bot.send_message(chat_id=chat_id, text=placeholder)
    
    full_text = ""
    last_update_time = 0
    update_interval = 0.15  # ~6fps refresh for smooth streaming display
    
    try:
        for chunk in friday.process_message_stream(user_text, image_path=image_path):
            full_text += chunk
            
            # Update message if interval has passed
            current_time = time.time()
            if current_time - last_update_time > update_interval:
                try:
                    if full_text.strip():
                        # Filter out internal tags before showing user
                        display_text = re.sub(r'(?:\[TOOL:|\*\*TOOL:).*?(?:\]|\*\*)', '', full_text, flags=re.DOTALL)
                        display_text = re.sub(r'(?:\[SEND_FILE:|\*\*SEND_FILE:).*?(?:\]|\*\*)', '', display_text, flags=re.DOTALL)
                        display_text = re.sub(r'(?:\[SEND_FILE_NOW:|\*\*SEND_FILE_NOW:).*?(?:\]|\*\*)', '', display_text, flags=re.DOTALL)
                        
                        if display_text.strip():
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=status_msg.message_id,
                                text=display_text + " ▌"
                            )
                        last_update_time = current_time
                except Exception:
                    pass
                    
        # Final update
        display_text = re.sub(r'(?:\[TOOL:|\*\*TOOL:).*?(?:\]|\*\*)', '', full_text, flags=re.DOTALL)
        # Handle [SEND_FILE_NOW: path] tag — file ready for direct delivery
        file_match = re.search(r'(?:\[SEND_FILE_NOW:|\*\*SEND_FILE_NOW:)\s*(.*?)(?:\]|\*\*)', full_text, flags=re.DOTALL)
        display_text = re.sub(r'(?:\[SEND_FILE:|\*\*SEND_FILE:).*?(?:\]|\*\*)', '', display_text, flags=re.DOTALL)
        display_text = re.sub(r'(?:\[SEND_FILE_NOW:|\*\*SEND_FILE_NOW:).*?(?:\]|\*\*)', '', display_text, flags=re.DOTALL).strip()
        
        if not display_text:
            display_text = "Done."

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=display_text
        )
        
        if file_match:
            file_path = file_match.group(1).strip()
            if (file_path.startswith('"') and file_path.endswith('"')) or \
               (file_path.startswith("'") and file_path.endswith("'")):
                file_path = file_path[1:-1]
            if os.path.exists(file_path):
                await context.bot.send_document(chat_id=chat_id, document=open(file_path, 'rb'))
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"I tried to send {os.path.basename(file_path)}, but it seems I misplaced it.")


    except Exception as e:
        logging.error(f"Error in process_and_respond: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Something went wrong internally. I'm looking into it.")
    finally:
        # Cleanup temp image if it exists
        if image_path and os.path.exists(image_path):
            try: os.remove(image_path)
            except: pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_and_respond(update, context, user_text=update.message.text)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the highest resolution photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    file_path = os.path.join(Config.TEMP_DIR, f"photo_{int(time.time())}.jpg")
    await file.download_to_drive(file_path)

    # Upload to Supabase Storage for persistence
    try:
        url = friday.executive.supabase.upload_file(file_path, bucket="friday-files")
        if url:
            logging.info(f"[Supabase] Uploaded photo: {url}")
    except Exception as e:
        logging.warning(f"[Supabase] Photo upload failed: {e}")

    caption = update.message.caption if update.message.caption else "Analyze this."
    await process_and_respond(update, context, user_text=caption, image_path=file_path)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # For now, we'll just acknowledge the voice and maybe transcribe later
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I hear you, but my ears are still a bit digital. Send me text or pictures for now while I tune my sensors.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    file = await context.bot.get_file(doc.file_id)
    temp_dir = os.path.abspath("temp")
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, doc.file_name or f"file_{int(time.time())}")
    await file.download_to_drive(file_path)

    # Upload to Supabase Storage for persistence
    try:
        url = friday.executive.supabase.upload_file(file_path, bucket="friday-files")
        if url:
            logging.info(f"[Supabase] Uploaded document: {url}")
    except Exception as e:
        logging.warning(f"[Supabase] Document upload failed: {e}")

    caption = update.message.caption if update.message.caption else "Parse this file and give me the data."
    await process_and_respond(update, context, user_text=f"[FILE: {file_path}] {caption}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Logs pollingerrors instead of crashing."""
    logging.error(f"Polling error (update {update.update_id if update else '?'}): {context.error}")

def build_application():
    """Creates and configures the Application instance."""
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    application = ApplicationBuilder().token(TOKEN).request(request).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_error_handler(error_handler)

    return application

if __name__ == '__main__':
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN not found in .env file.")
        exit(1)

    retry_delay = 1
    max_retry_delay = 30

    while True:
        try:
            application = build_application()
            print("Friday is online and listening...")
            application.run_polling()
            break  # clean shutdown
        except Exception as e:
            logging.error(f"Polling crashed: {type(e).__name__}: {e}")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
            logging.info(f"Restarting polling in {retry_delay}s...")
