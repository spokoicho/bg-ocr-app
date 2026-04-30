import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import shutil
import os

# Настройка
st.set_page_config(page_title="BG OCR", page_icon="📄")
st.title("📄 Български OCR Екстракторp")

# Проверка дали Tesseract е инсталиран правилно в системата
tesseract_path = shutil.which("tesseract")
poppler_path = shutil.which("pdftoppm")

if not tesseract_path:
    st.error("❌ Tesseract не е намерен в системата! Проверете packages.txt.")
if not poppler_path:
    st.warning("⚠️ Poppler (pdftoppm) не е намерен. PDF конвертирането може да се провали.")

uploaded_file = st.file_uploader("Качете сканиран PDF", type=["pdf"])

if uploaded_file is not None:
    if st.button("🚀 Извлечи текста"):
        try:
            with st.spinner('Превръщане на PDF в текст...'):
                # Четем файла
                pdf_content = uploaded_file.read()
                
                # Конвертиране (ако Poppler е в пътя, ще работи директно)
                images = convert_from_path(pdf_content, dpi=300)
                
                full_text = ""
                for i, img in enumerate(images):
                    # OCR процес
                    text = pytesseract.image_to_string(img, lang='bul')
                    full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                
                if full_text.strip() == "":
                    st.warning("⚠️ Не беше открит текст. Сигурни ли сте, че файлът съдържа сканирани изображения?")
                else:
                    st.success("Готово!")
                    st.text_area("Резултат:", full_text, height=400)
                    st.download_button("💾 Изтегли .txt", full_text.encode('utf-8'), "result.txt")
                    
        except Exception as e:
            st.error(f"Грешка при обработката: {str(e)}")
            st.info("Ако виждате грешка 'PDFInfoNotInstalled', значи Poppler не е зареден правилно.")
