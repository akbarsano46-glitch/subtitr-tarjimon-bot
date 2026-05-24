import os
import re
import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
import google.generativeai as genai

# Xatoliklarni konsolda ko'rish uchun logging
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8950662044:AAEGDW7OvBPa_0oRC1k9SD_I7M237JSWOUk"
GEMINI_API_KEY = "AIzaSyBwZ3UBa5ZEVgy6587b1bP1CA_O9yajj-8"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# 1. Gemini orqali paketli tarjima qilish funksiyasi
async def translate_batch(lines: list) -> list:
    if not lines:
        return []
    
    # Qatorlarni raqamlab, bitta matn holiga keltiramiz
    prepared_text = "\n".join([f"[{i}] {line}" for i, line in enumerate(lines)])
    
    prompt = (
        "Siz professional subtitr tarjimonisiz. Quyidagi raqamlangan matnlarni o'zbek tiliga tarjima qiling.\n"
        "Qoidalarga qat'iy amal qiling:\n"
        "1. Tarjima juda tabiiy, jonli va dublyaj hamda lab harakatlariga (lip-sync) mos, o'zbek adabiy tili qoidalarida bo'lsin.\n"
        "2. Har bir qatorning boshidagi [0], [1] kabi indeks raqamlarini aslo o'zgartirmang va o'chirmang. Tarjimani o'sha indeks bilan qaytaring.\n"
        "3. Matn ichidagi maxsus kodlar (masalan: {\\an8}, \\N, {\\i1}) o'zgarishsiz o'z joyida qolsin.\n"
        "4. Faqat va faqat tarjima qilingan raqamli qatorlarni qaytaring, hech qanday izoh yoki qo'shimcha gap yozmang.\n\n"
        f"Matnlar:\n{prepared_text}"
    )
    
    try:
        response = await model.generate_content_async(prompt)
        translated_raw = response.text.strip().split("\n")
        
        # Qayta tiklash uchun lug'at yaratamiz
        result_dict = {}
        for r_line in translated_raw:
            match = re.match(r"^\[(\d+)\]\s*(.*)", r_line.strip())
            if match:
                idx = int(match.group(1))
                val = match.group(2)
                result_dict[idx] = val
        
        # Agar Gemini qaysidir qatorni o'tkazib yuborgan bo'lsa, asl holini qoldiramiz
        final_lines = []
        for i in range(len(lines)):
            final_lines.append(result_dict.get(i, lines[i]))
        return final_lines
        
    except Exception as e:
        logging.error(f"Gemini Tarjima Xatosi: {e}")
        return lines # Xatolik bo'lsa asl holini qaytaradi

# 2. SRT faylni qayta ishlash
async def process_srt(content: str) -> str:
    # SRT bloklarini ajratish
    blocks = content.replace('\r\n', '\n').split('\n\n')
    translated_blocks = []
    
    batch_lines = []
    batch_meta = [] # Qaysi blokga tegishliligini bilish uchun
    
    for block_idx, block in enumerate(blocks):
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            # 0: ID, 1: Vaqt, 2+: Matn
            text_lines = "\n".join(lines[2:])
            batch_lines.append(text_lines)
            batch_meta.append((block_idx, lines[0], lines[1]))
        else:
            translated_blocks.append((block_idx, block))
            
    # API yuklamasini kamaytirish uchun 30 qatordan bo'lib tarjima qilamiz
    chunk_size = 30
    for i in range(0, len(batch_lines), chunk_size):
        chunk_lines = batch_lines[i:i+chunk_size]
        translated_chunk = await translate_batch(chunk_lines)
        
        for j, tr_text in enumerate(translated_chunk):
            b_idx, s_id, s_time = batch_meta[i+j]
            full_block = f"{s_id}\n{s_time}\n{tr_text}"
            translated_blocks.append((b_idx, full_block))
        await asyncio.sleep(1) # API limitga tushmaslik uchun kichik pauza
        
    # Bloklarni asl ketma-ketligida yig'ish
    translated_blocks.sort(key=lambda x: x[0])
    return "\n\n".join([b[1] for b in translated_blocks])

# 3. ASS faylni qayta ishlash
async def process_ass(content: str) -> str:
    lines = content.replace('\r\n', '\n').split('\n')
    translated_lines = []
    
    batch_lines = []
    batch_meta = []
    
    for idx, line in enumerate(lines):
        if line.startswith("Dialogue:"):
            # Dialogue: Marked,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
            parts = line.split(",", 9)
            if len(parts) == 10:
                meta = parts[:9]
                text = parts[9]
                batch_lines.append(text)
                batch_meta.append((idx, meta))
            else:
                translated_lines.append((idx, line))
        else:
            translated_lines.append((idx, line))
            
    chunk_size = 30
    for i in range(0, len(batch_lines), chunk_size):
        chunk_lines = batch_lines[i:i+chunk_size]
        translated_chunk = await translate_batch(chunk_lines)
        
        for j, tr_text in enumerate(translated_chunk):
            orig_idx, meta = batch_meta[i+j]
            full_line = ",".join(meta) + "," + tr_text
            translated_lines.append((orig_idx, full_line))
        await asyncio.sleep(1)
        
    translated_lines.sort(key=lambda x: x[0])
    return "\n".join([l[1] for l in translated_lines])

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 Salom! Men professional subtitr tarjimoniman.\n"
        "Menga `.srt` yoki `.ass` formatidagi faylni yuboring, uni yuqori sifatda, "
        "vaqtlari va stillarini buzmasdan o'zbek tiliga tarjima qilib beraman."
    )

@dp.message(F.document)
async def handle_docs(message: types.Message):
    file_name = message.document.file_name

    if not (file_name.endswith('.srt') or file_name.endswith('.ass')):
        await message.answer("❌ Iltimos, faqat `.srt` yoki `.ass` formatidagi fayllarni yuboring.")
        return

    msg = await message.answer("📥 Fayl qabul qilindi. Jarayon boshlanmoqda...")

    file = await bot.get_file(message.document.file_id)
    downloaded_file = await bot.download_file(file.file_path)
    content = downloaded_file.read().decode('utf-8', errors='ignore')

    await msg.edit_text("⏳ Gemini API yordamida o'ta aniqlikda tarjima qilinmoqda...\nFayl hajmiga qarab bu biroz vaqt olishi mumkin.")

    try:
        if file_name.endswith('.srt'):
            output_content = await process_srt(content)
        else:
            output_content = await process_ass(content)
            
        out_file_name = f"uz_{file_name}"
        with open(out_file_name, "w", encoding="utf-8") as f:
            f.write(output_content)

        await msg.edit_text("✅ Tarjima yakunlandi! Fayl yuborilmoqda...")
        document = types.FSInputFile(out_file_name)
        await message.reply_document(document, caption="🎉 Subtitr muvaffaqiyatli tarjima qilindi!")
        
        os.remove(out_file_name)
    except Exception as e:
        logging.error(f"Xatolik yuz berdi: {e}")
        await message.answer("❌ Afsuski, faylni qayta ishlashda xatolik yuz berdi.")
    finally:
        await msg.delete()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
