import streamlit as st
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import io

# Конфигурация на страницата
st.set_page_config(page_title="OCR Български", page_icon="📄")

st.title("📄 Извличане на текст от сканиран PDF")
st.write("Това приложение използва Tesseract OCR за разпознаване на български език.")

# Качване на файл
uploaded_file = st.file_uploader("Изберете сканиран PDF файл", type=["pdf"])

if uploaded_file is not None:
    if st.button("🚀 Започни извличането"):
        try:
            with st.spinner('Превръщане на PDF страниците в изображения...'):
                # Четем байтовете на файла
                pdf_content = uploaded_file.read()
                # Конвертираме PDF в списък от изображения
                images = convert_from_path(pdf_content, dpi=300)
            
            full_text = ""
            progress_text = st.empty()
            progress_bar = st.progress(0)
            
            for i, image in enumerate(images):
                progress_text.text(f"Обработка на страница {i+1} от {len(images)}...")
                
                # Извличане на текст (OCR)
                # Използваме 'bul' за български език
                text = pytesseract.image_to_string(image, lang='bul')
                
                full_text += f"--- Страница {i+1} ---\n{text}\n\n"
                
                # Обновяване на прогреса
                progress_bar.progress((i + 1) / len(images))
            
            st.success("Готово!")
            
            # Показване на текста в приложението
            st.text_area("Извлечен текст:", full_text, height=400)
            
            # Бутон за изтегляне
            st.download_button(
                label="💾 Изтегли като .txt",
                data=full_text.encode('utf-8'),
                file_name="izvlechen_tekst.txt",
                mime="text/plain"
            )

        except Exception as e:
            # Използваме директно стринговата репрезентация на e, 
            # за да избегнем проблеми с локални променливи
            st.error(f"Възникна грешка при обработката: {str(e)}")
            st.info("💡 Уверете се, че файловете 'requirements.txt' и 'packages.txt' са правилно настроени в GitHub.")

st.divider()
st.caption("Технологии: Streamlit, Tesseract OCR, Poppler")
