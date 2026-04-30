import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import shutil

st.set_page_config(page_title="Български OCR", layout="centered")
st.title("📄 Български OCR Екстрактор")

# Проверка на пътищата
tesseract_path = shutil.which("tesseract")
poppler_path = shutil.which("pdftoppm")

if not tesseract_path:
    st.error("❌ Tesseract не е намерен!")
if not poppler_path:
    st.warning("⚠️ Poppler не е намерен!")

uploaded_file = st.file_uploader("Качете сканиран PDF", type=["pdf"])

if uploaded_file is not None:
    if st.button("🚀 Извлечи текста"):
        try:
            with st.spinner('Обработка...'):
                # Директно подаваме байтовете на файла
                images = convert_from_path(uploaded_file.read())
                
                full_text = ""
                for i, img in enumerate(images):
                    # Важно: използваме 'bul' за български
                    text = pytesseract.image_to_string(img, lang='bul')
                    full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                
                if full_text.strip():
                    st.success("Готово!")
                    st.text_area("Резултат:", full_text, height=400)
                    st.download_button("📥 Изтегли .txt", full_text.encode('utf-8'), "result.txt")
                else:
                    st.warning("Не беше открит текст.")
                    
        except Exception as e:
            # Използваме директно форматиране, за да избегнем грешки с обхвата на променливите
            error_message = str(e)
            st.error(f"Критична грешка: {error_message}")
            st.info("Възможна причина: Файлът е твърде голям или Poppler не може да го прочете.")
