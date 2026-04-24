import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import io
from PIL import Image

# Настройка на заглавието на страницата
st.set_page_config(page_title="BG OCR Екстрактор", page_icon="📄")

st.title("📄 Извличане на текст от сканиран PDF")
st.markdown("---")
st.write("Качете сканиран PDF файл, за да извлечете текста на български език.")

# Поле за качване на файл
uploaded_file = st.file_uploader("Изберете PDF файл", type=["pdf"])

if uploaded_file is not None:
    # Бутон за стартиране
    if st.button("🚀 Започни извличането"):
        with st.spinner('Обработка... Превръщане на страниците в текст...'):
            try:
                # 1. Четене на качения файл
                pdf_bytes = uploaded_file.read()
                
                # 2. Конвертиране на PDF към изображения (изисква Poppler)
                # Използваме 300 DPI за по-добра точност при българския текст
                images = convert_from_path(pdf_bytes, dpi=300)
                
                full_text = ""
                num_pages = len(images)
                
                # Прогрес бар
                progress_bar = st.progress(0)
                
                for i, image in enumerate(images):
                    # 3. OCR процес с Tesseract за български ('bul')
                    # Може да добавите 'bul+eng' ако има и английски думи
                    page_text = pytesseract.image_to_string(image, lang='bul')
                    
                    full_text += f"--- СТРАНИЦА {i+1} ---\n"
                    full_text += page_text + "\n\n"
                    
                    # Обновяване на прогреса
                    progress_bar.progress((i + 1) / num_pages)
                
                # 4. Показване на резултатите
                st.success("Текстът е извлечен успешно!")
                
                # Поле за преглед на текста
                st.text_area("Резултат:", value=full_text, height=400)
                
                # Бутон за изтегляне
                st.download_button(
                    label="💾 Изтегли като .txt файл",
                    data=full_text,
                    file_name="izvlechen_tekst.txt",
                    mime="text/plain"
                )

            except Exception as e:
                error_msg = str(e)
                if "tesseract" in error_msg.lower():
                    st.error("❌ Грешка: Tesseract не е намерен. Уверете се, че имате packages.txt с 'tesseract-ocr' и 'tesseract-ocr-bul'.")
                elif "poppler" in error_msg.lower():
                    st.error("❌ Грешка: Poppler не е намерен. Уверете се, че имате packages.txt с 'poppler-utils'.")
                else:
                    st.error(f"⚠️ Възникна неочаквана грешка: {error_msg}")

st.markdown("---")
st.caption("Разработено с Python, Streamlit и Tesseract OCR")
