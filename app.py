import streamlit as st
import pytesseract
from pdf2image import convert_from_path
import io

# Настройка
st.set_page_config(page_title="BG OCR", page_icon="📄")

st.title("📄 Извличане на текст (Български)")

uploaded_file = st.file_uploader("Качете PDF", type=["pdf"])

if uploaded_file is not None:
    if st.button("🚀 Стартирай"):
        try:
            # Четене на файла
            file_bytes = uploaded_file.read()
            
            with st.spinner('Обработка...'):
                # PDF към изображения
                images = convert_from_path(file_bytes, dpi=300)
                
                result_text = ""
                for i, img in enumerate(images):
                    # OCR на български
                    page_content = pytesseract.image_to_string(img, lang='bul')
                    result_text += f"--- Страница {i+1} ---\n{page_content}\n\n"
                
                st.success("Готово!")
                st.text_area("Извлечен текст:", result_text, height=400)
                
                st.download_button(
                    label="💾 Изтегли текста",
                    data=result_text.encode('utf-8'),
                    file_name="text.txt",
                    mime="text/plain"
                )
        except Exception as e:
            # Използваме 'e', а не 'err', за да няма конфликти
            st.error(f"Грешка: {str(e)}")
