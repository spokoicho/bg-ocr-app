import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import shutil
import sys
import tempfile

st.set_page_config(page_title="Български OCR", layout="centered")
st.title("📄 Български OCR Екстрактор")

t_path = shutil.which("tesseract")
p_path = shutil.which("pdftoppm")

if not t_path:
    st.error("❌ Tesseract не е намерен в системата!")
if not p_path:
    st.error("❌ Poppler (pdftoppm) не е намерен! OCR няма да работи.")

uploaded_file = st.file_uploader("Качете сканиран PDF", type=["pdf"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()

    if st.button("🚀 Извлечи текста"):
        try:
            # Записваме PDF временно
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            with st.spinner('Конвертиране на PDF в изображения...'):
                images = convert_from_path(
                    tmp_path,
                    dpi=300,
                    poppler_path=p_path.replace("pdftoppm", "")
                )

            full_text = ""
            progress_bar = st.progress(0)

            for i, img in enumerate(images):
                text = pytesseract.image_to_string(img, lang='bul')
                full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                progress_bar.progress((i + 1) / len(images))

            if full_text.strip():
                st.success("Обработката завърши!")
                st.text_area("Резултат:", full_text, height=400)
                st.download_button("📥 Изтегли .txt", full_text.encode('utf-8'), "result.txt")
            else:
                st.warning("Не беше открит текст в документа.")

        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            st.error(f"⚠️ Истинската грешка е: {exc_value}")
            st.info("Ако грешката е 'PDFInfoNotInstalledError', значи Poppler не е в системния път.")
