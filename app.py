import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

# --- КОНФИГУРАЦИЯ ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1DxuWAgGtTwGUFxy_nntqDb_lMYbJVyTC1NSS3Rk62ps/edit?usp=sharing"
st.set_page_config(page_title="UBB Smart Converter", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

def load_mappings():
    try:
        df = conn.read(spreadsheet=SHEET_URL, ttl="5s")
        return dict(zip(df["Original"], df["Replacement"]))
    except:
        return {}

def save_mappings(mappings):
    new_df = pd.DataFrame([{"Original": k, "Replacement": v} for k, v in mappings.items()])
    conn.update(spreadsheet=SHEET_URL, data=new_df)
    st.cache_data.clear()

def preprocess_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return gray

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""
    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        full_text += pytesseract.image_to_string(processed, lang="bul+eng", config='--psm 6') + "\n"
    return full_text

def parse_statement(text, mappings):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    transactions = []
    
    for i, line in enumerate(lines):
        # 1. КОРИГИРАНА ДАТА: Превръща 01/01/26 в 01/01/2026
        date_match = re.match(r"^(\d{2}/\d{2}/)(\d{2,4})", line)
        if date_match:
            day_month = date_match.group(1)
            year = date_match.group(2)
            full_year = year if len(year) == 4 else f"20{year}"
            formatted_date = f"{day_month}{full_year}"

            # 2. ФИКС НА СУМИТЕ: Търсим число преди "EUR"
            # Премахваме интервали и заменяме запетая с точка за правилно изчисление
            clean_line = line.replace(" ", "").replace(",", ".")
            amt_match = re.search(r"(-?\d+\.\d{2})EUR", clean_line)
            
            amount = 0.0
            if amt_match:
                amount = float(amt_match.group(1))

            # 3. ДЕТАЙЛИ И ЗАМЕНИ
            raw_name = lines[i+1] if i+1 < len(lines) else ""
            raw_rem = lines[i+2] if i+2 < len(lines) else ""
            
            name = mappings.get(raw_name, raw_name)
            rem = mappings.get(raw_rem, raw_rem)
            
            transactions.append({
                "ДАТА": formatted_date,
                "ОРИГИНАЛЕН ТЕКСТ": raw_name,
                "ВИД": "ОПЕРАЦИЯ", # Може да се автоматизира според ключови думи
                "НАРЕДИТЕЛ/ПОЛУЧАТЕЛ": name,
                "ОСНОВАНИЕ": rem,
                "СУМА": amount,
                "ТИП": "Кредит" if amount > 0 else "Дебит"
            })
    return transactions

# --- UI ---
st.title("🏦 UBB Smart Converter")

if 'mappings' not in st.session_state:
    st.session_state.mappings = load_mappings()

uploaded_file = st.file_uploader("Качете PDF извлечение", type="pdf")

if uploaded_file:
    if st.button("🚀 Анализирай файла"):
        with st.spinner("Обработка на суми и дати..."):
            raw_text = ocr_pdf(uploaded_file.read())
            data = parse_statement(raw_text, st.session_state.mappings)
            st.session_state.df = pd.DataFrame(data)

if 'df' in st.session_state:
    # ИНТЕРАКТИВНА ТАБЛИЦА
    st.subheader("📝 Редактиране на трансакции")
    
    # Конфигурираме колоните, за да изглеждат професионално
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
        if st.button("💾 Запамети преименуванията в Google Sheets"):
            new_rules = {}
            for _, row in edited_df.iterrows():
                orig = row["ОРИГИНАЛЕН ТЕКСТ"]
                curr = row["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                if orig != curr and orig != "":
                    new_rules[orig] = curr
            
            if new_rules:
                st.session_state.mappings.update(new_rules)
                save_mappings(st.session_state.mappings)
                st.success(f"Обновени са {len(new_rules)} правила!")

    with col2:
        if st.button("⚙️ Генерирай XML"):
            root = ET.Element("STATEMENT")
            for _, r in edited_df.iterrows():
                t = ET.SubElement(root, "TRANSACTION")
                ET.SubElement(t, "POST_DATE").text = r["ДАТА"]
                tag = "AMOUNT_C" if r["ТИП"] == "Кредит" else "AMOUNT_D"
                ET.SubElement(t, tag).text = str(abs(r["СУМА"]))
                ET.SubElement(t, "NAME_R").text = r["НАРЕДИТЕЛ/ПОЛУЧАТЕЛ"]
                ET.SubElement(t, "REM_I").text = r["ОСНОВАНИЕ"]
            
            xml_str = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="  ")
            st.download_button("📥 Свали XML", xml_str, "statement.xml", "text/xml")
