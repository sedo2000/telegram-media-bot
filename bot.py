import os
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from PIL import Image
from moviepy.editor import VideoFileClip
from pydub import AudioSegment

# إعداد السجلات (Logging)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- جلب المتغيرات من بيئة Vercel ---
# هذه المتغيرات ستقوم بإضافتها في إعدادات مشروع Vercel
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

app_flask = Flask(__name__)
telegram_app = None


@app_flask.route("/", methods=["GET"])
def index():
    return "Telegram Bot is running smoothly on Vercel!", 200


@app_flask.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, telegram_app.bot)
        telegram_app.update_queue.put(update)
    return "OK", 200


# دالة البدء /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "مرحباً بك في بوت التحويل الشامل!\n\n"
        "أرسل لي أي ملف وسأقوم بتحويله:\n"
        "• بصمة ↔️ MP3\n"
        "• صورة ➔ ملصق + PNG (512x512)\n"
        "• ملصق ➔ صورة\n"
        "• فيديو ➔ صوت (MP3) + فيديو متحرك (GIF)\n"
        "• فيديو نوت ➔ فيديو عادي + بصمة صوتية\n"
        "• فيديو ➔ فيديو نوت (دائري)\n"
    )
    await update.message.reply_text(welcome_text)


# معالجة الوسائط
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat.id
    
    # استخدام /tmp وهو المسار المسموح للكتابة فيه على Vercel Serverless
    temp_dir = "/tmp" 

    try:
        # 1. بصمة صوتية أو ملف صوتي
        if message.voice or message.audio:
            file = await (message.voice or message.audio).get_file()
            input_path = os.path.join(temp_dir, f"{chat_id}_audio_in")
            await file.download_to_drive(input_path)

            keyboard = [
                [InlineKeyboardButton("تغيير العنوان", callback_data="edit_title"),
                 InlineKeyboardButton("تغيير الفنان", callback_data="edit_artist")],
                [InlineKeyboardButton("تغيير الوصف", callback_data="edit_desc"),
                 InlineKeyboardButton("تغيير الصورة المصغرة", callback_data="edit_thumb")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if message.voice:
                output_path = os.path.join(temp_dir, f"{chat_id}_audio_out.mp3")
                audio = AudioSegment.from_file(input_path, format="ogg")
                audio.export(output_path, format="mp3")
                await message.reply_audio(audio=open(output_path, "rb"), caption="تم التحويل لـ MP3!", reply_markup=reply_markup)
            else:
                output_path = os.path.join(temp_dir, f"{chat_id}_audio_out.ogg")
                audio = AudioSegment.from_file(input_path)
                audio.export(output_path, format="ogg", codec="libopus")
                await message.reply_voice(voice=open(output_path, "rb"), caption="تم التحويل لبصمة!")
            return

        # 2. صورة
        if message.photo:
            photo = message.photo[-1]
            file = await photo.get_file()
            input_path = os.path.join(temp_dir, f"{chat_id}_img.jpg")
            await file.download_to_drive(input_path)

            img = Image.open(input_path)
            img.thumbnail((512, 512))
            new_img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            paste_x, paste_y = (512 - img.width) // 2, (512 - img.height) // 2
            new_img.paste(img, (paste_x, paste_y))

            png_path = os.path.join(temp_dir, f"{chat_id}_centered.png")
            webp_path = os.path.join(temp_dir, f"{chat_id}_sticker.webp")
            new_img.save(png_path, "PNG")
            new_img.save(webp_path, "WEBP")

            await message.reply_document(document=open(png_path, "rb"), caption="صورة PNG مع التوسيط")
            await message.reply_sticker(sticker=open(webp_path, "rb"))
            return

        # 3. ملصق
        if message.sticker and not message.sticker.is_animated:
            file = await message.sticker.get_file()
            webp_path = os.path.join(temp_dir, f"{chat_id}_sticker.webp")
            png_path = os.path.join(temp_dir, f"{chat_id}_from_sticker.png")
            await file.download_to_drive(webp_path)

            img = Image.open(webp_path).convert("RGB")
            img.save(png_path, "PNG")
            await message.reply_photo(photo=open(png_path, "rb"), caption="الصورة المستخرجة من الملصق")
            return

        # 4. فيديو نوت
        if message.video_note:
            file = await message.video_note.get_file()
            mp4_path = os.path.join(temp_dir, f"{chat_id}_vnote.mp4")
            await file.download_to_drive(mp4_path)

            clip = VideoFileClip(mp4_path)
            audio_path = os.path.join(temp_dir, f"{chat_id}_vnote_audio.ogg")
            clip.audio.write_audiofile(audio_path, codec="libopus")

            await message.reply_video(video=open(mp4_path, "rb"), caption="فيديو عادي")
            await message.reply_voice(voice=open(audio_path, "rb"), caption="البصمة الصوتية")
            return

        # 5. فيديو عادي
        if message.video:
            file = await message.video.get_file()
            video_path = os.path.join(temp_dir, f"{chat_id}_video.mp4")
            await file.download_to_drive(video_path)

            clip = VideoFileClip(video_path)
            audio_mp3 = os.path.join(temp_dir, f"{chat_id}_audio.mp3")
            clip.audio.write_audiofile(audio_mp3)

            gif_path = os.path.join(temp_dir, f"{chat_id}_anim.gif")
            clip.subclip(0, min(5, clip.duration)).write_gif(gif_path, fps=15)

            vnote_path = os.path.join(temp_dir, f"{chat_id}_vnote_out.mp4")
            w, h = clip.size
            min_dim = min(w, h)
            square_clip = clip.crop(
                x1=(w - min_dim)/2, y1=(h - min_dim)/2, 
                x2=(w + min_dim)/2, y2=(h + min_dim)/2
            ).resize((384, 384))
            square_clip.write_videofile(vnote_path, codec="libx264", audio_codec="aac", preset="ultrafast")

            await message.reply_audio(audio=open(audio_mp3, "rb"), caption="الصوت المستخرج")
            await message.reply_animation(animation=open(gif_path, "rb"), caption="صورة متحركة (5 ثوانٍ)")
            await message.reply_video_note(video_note=open(vnote_path, "rb"))
            return

    except Exception as e:
         logger.error(f"Error processing media: {e}")
         await message.reply_text("حدث خطأ أثناء المعالجة. يرجى المحاولة لاحقاً.")


# تفاعل الأزرار
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "edit_title":
        await query.message.reply_text("أرسل العنوان الجديد:")
    elif query.data == "edit_artist":
        await query.message.reply_text("أرسل اسم الفنان الجديد:")
    elif query.data == "edit_desc":
        await query.message.reply_text("أرسل الوصف الجديد:")
    elif query.data == "edit_thumb":
        await query.message.reply_text("أرسل الصورة المصغرة الجديدة:")

# إعداد التطبيق للعمل مع Webhook
def main():
    global telegram_app
    
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set!")
        return

    telegram_app = Application.builder().token(TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO | filters.PHOTO | filters.STICKER | filters.VIDEO_NOTE | filters.VIDEO,
            handle_media,
        )
    )
    telegram_app.add_handler(CallbackQueryHandler(button_callback))

    if WEBHOOK_URL:
        # إعداد Webhook
        full_webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
        telegram_app.bot.set_webhook(url=full_webhook_url)
        logger.info(f"Webhook set to: {full_webhook_url}")
        
        # تشغيل سيرفر Flask
        port = int(os.environ.get("PORT", 5000))
        app_flask.run(host="0.0.0.0", port=port)
    else:
        logger.warning("WEBHOOK_URL is not set. Running in polling mode (Not recommended for Vercel).")
        telegram_app.run_polling()

if __name__ == "__main__":
    main()
