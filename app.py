import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom
import json
import os

# --- КОНФИГУРАЦИЯ И ПАМЕТ ---
st.set_page_config(page_title="UBB Smart Converter", layout="wide")
MAPPING_FILE = "smart_mappings.json"

def load_mappings():
    """Зарежда историята на вашите преименувания."""
    if os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_mappings(mappings):
    """Запаметява преименуванията за бъдещи сесии."""
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mappings, f, ensure_ascii=False, indent=4)

# Инициализация на състоянието
if 'mappings' not in st.session_state:
    st.session_state.mappings = load_mappings()
if 'df' not in st.session_state:
    st.session_state.df = None
if 'iban' not in st.session_state:
    st.session_state.iban = ""

# --- OCR ФУНКЦИИ ---
def preprocess_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, thresh = cv2.threshold(denoised, 180, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""
    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        text = pytesseract.image_to_string(processed, lang="bul+eng", config='--oem 3 --psm 6')
        full_text += text + "\n"
    return full_text.replace("CENA", "СЕПА").replace("580.", "SBD.")

def parse_obb_statement(text):
    """Парсване и автоматична замяна на текст[cite: 2, 4, 5]."""
    iban_match = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    iban = iban_match.group(1) if iban_match else "Неизвестен"
    
    transactions = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    i = 0
    while i < len(lines):
        line = lines[i]
        date_match = re.match(r"^(\d{2}/\d{2}/\d{2,4})", line)
        
        if date_match:
            tr = {
                "ДАТА": date_match.group(1),
                "ЧАС": "null",
                "ВИД": "ОПЕРАЦИЯ",
                "НАРЕДИТЕЛ/ПОЛУЧАТЕЛ": "null",
                "ОСНОВАНИЕ": "null",
                "СУМА": 0.0,
                "ТИП": "Дебит"
            }
            
            # Извличане на сума[cite: 2, 5]
            amt_match = re.search(r"(-?[\d\s,]+\.\d{2})\s*EUR", line.replace(",", ""))
            if amt_match:
                val = float(amt_match.group(1).replace(" ", ""))
                tr["СУМА"] = val
                tr["ТИП"] = "Кредит" if val > 0 else "Дебит"

            # Определяне на Вид
            for keyword in ["СЕПА ПОЛУЧЕН", "ИЗХОДЯЩ ПРЕВОД", "МЕСЕЧНА ТАКСА", "ПРЕВАЛУТИРАНЕ", "ТЕГЛЕНЕ"]:
                if keyword in line.upper():
                    tr["ВИД"] = keyword
                    break

            # Четене на следващи редове за детайли[cite: 2, 5]
            curr_j = i + 1
            details = []
            while curr_j < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2}", lines[curr_j]):
                orig_text = lines[curr_j]
                # АВТОМАТИЧНА ЗАМЯНА: Ако текстът съществува в базата, го сменяме веднага[cite: 4]
                replaced_text = st.session_state.mappings.get(orig_text, orig_text)
                details.append(replaced_text)
                curr_j += 1
            
            if len(details) >= 1: tr["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"] = details[0]
            if len(details) >= 2: tr["ОСНОВАНИЕ"] = details[1]
            
            transactions.append(tr)
            i = curr_j - 1
        i += 1
    return iban, transactions

# --- UI ЧАСТ ---
st.title("🏦 Смарт Конвертор ОББ (с памет)")
st.markdown("Редактирайте клетките директно. Приложението ще запомни промените ви за в бъдеще[cite: 1, 4].")

uploaded_file = st.file_uploader("Качете банково извлечение (PDF)", type="pdf")

if uploaded_file:
    # Обработка само при ново качване
    if st.button("🚀 Анализирай файла") or st.session_state.df is None:
        with st.spinner('OCR обработка и прилагане на запаметени правила...'):
            raw_text = ocr_pdf(uploaded_file.read())
            iban, trs = parse_obb_statement(raw_text)
            st.session_state.iban = iban
            st.session_state.df = pd.DataFrame(trs)

if st.session_state.df is not None:
    # ИНТЕРАКТИВНА ТАБЛИЦА[cite: 1, 4]
    st.subheader("📝 Редактиране на данни")
    edited_df = st.data_editor(
        st.session_state.df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "СУМА": st.column_config.NumberColumn(format="%.2f EUR"),
            "ТИП": st.column_config.SelectboxColumn(options=["Дебит", "Кредит"])
        }
    )

    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("💾 Запамети новите имена в паметта"):
            # Логика за намиране на разликите и запис в mappings[cite: 4]
            new_maps = 0
            for i in range(len(edited_df)):
                orig_n = st.session_state.df.iloc[i]["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                edit_n = edited_df.iloc[i]["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                if orig_n != edit_n and orig_n != "null":
                    st.session_state.mappings[orig_n] = edit_n
                    new_maps += 1
                
                orig_o = st.session_state.df.iloc[i]["ОСНОВАНИЕ"]
                edit_o = edited_df.iloc[i]["ОСНОВАНИЕ"]
                if orig_o != edit_o and orig_o != "null":
                    st.session_state.mappings[orig_o] = edit_o
                    new_maps += 1
            
            save_mappings(st.session_state.mappings)
            st.success(f"Успешно запаметени {new_maps} нови правила за автоматична замяна!")

    with col2:
        # ГЕНЕРИРАНЕ НА XML[cite: 4]
        if st.button("⚙️ Генерирай XML"):
            root = ET.Element("STATEMENT")
            ET.SubElement(root, "IBAN_S").text = st.session_state.iban
            for _, row in edited_df.iterrows():
                t = ET.SubElement(root, "TRANSACTION")
                ET.SubElement(t, "POST_DATE").text = row["ДАТА"]
                tag = "AMOUNT_C" if row["ТИП"] == "Кредит" else "AMOUNT_D"
                ET.SubElement(t, tag).text = str(abs(row["СУМА"]))
                ET.SubElement(t, "TR_NAME").text = row["ВИД"]
                ET.SubElement(t, "NAME_R").text = row["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                ET.SubElement(t, "REM_I").text = row["ОСНОВАНИЕ"]
            
            xml_str = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="  ")
            st.download_button("📥 Свали XML", xml_str, "statement_final.xml", "text/xml")

    # Стилизиран преглед (подобно на image_2f7274.png)[cite: 4]
    st.divider()
    st.subheader("👀 Финален изглед")
    
    def color_rows(val):
        color = 'green' if val > 0 else 'red'
        return f'color: {color}; font-weight: bold'

    final_view = edited_df.copy()
    # Форматиране на сумата със знаци + / -[cite: 4]
    final_view["СУМА"] = final_view.apply(lambda r: f"{'+' if r['СУМА'] > 0 else ''}{r['СУМА']:.2f}", axis=1)
    st.table(final_view)
