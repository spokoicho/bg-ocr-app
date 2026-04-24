import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import io
from PIL import Image

# Конфигурация на страницата
st.set_page_config(page_title="BG OCR Екстрактор", page_icon="📄")

st.title("📄 Извличане на текст от сканиран PDF")
st.subheader("С поддръжка на български език")

# Поле за качване на файл
uploaded_file = st.file_uploader("Качете сканиран PDF файл", type=["pdf"])

if uploaded_file is not None:
    if st.button("Започни извличането"):
        with st.spinner('Обработка... Моля изчакайте (зависи от броя страници)'):
            try:
                # Четене на байтовете на качения файл
                pdf_bytes = uploaded_file.read()
                
                # Конвертиране на PDF към изображения
                # Забележка: На сървъра трябва да има инсталиран Poppler
                images = convert_from_path(pdf_bytes)
                
                full_text = ""
                progress_bar = st.progress(0)
                
                for i, image in enumerate(images):
                    # OCR процес за всяка страница
                    text = pytesseract.image_to_string(image, lang='bul')
                    full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                    
                    # Актуализиране на прогреса
                    progress = (i + 1) / len(images)
                    progress_bar.progress(progress)

                # Показване на резултата
                st.success("Готово!")
                st.text_area("Извлечен текст:", full_text, height=400)
                
                # Бутон за изтегляне на резултата
                st.download_button(
                    label="Изтегли текста като .txt",
                    data=full_text,
                    file_name="izvlechen_tekst.txt",
                    mime="text/plain"
                )
                
                except Exception as e:
                # Тук проверяваме какво точно се е объркало
                error_message = str(e)
                if "tesseract" in error_message.lower():
                    st.error("❌ Tesseract OCR не е инсталиран на сървъра. Проверете дали имате файл packages.txt.")
                elif "poppler" in error_message.lower():
                    st.error("❌ Poppler не е инсталиран (нужен е за PDF). Проверете дали имате файл packages.txt.")
                else:
                    st.error(f"Възникна грешка: {error_message}")

st.info("Забележка: Уверете се, че документът е добре осветен и четлив за по-добри резултати.")
