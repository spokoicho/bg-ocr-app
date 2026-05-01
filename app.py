import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
import sys
import shutil

# --- КОНФИГУРАЦИЯ НА СТРАНИЦАТА ---
st.set_page_config(page_title="ОББ PDF -> XML", layout="wide")
st.title("📄 ОББ Извлечение: PDF към XML")

# --- 1. OCR И ПРЕДВАРИТЕЛНА ОБРАБОТКА (ROW-BASED) ---

def preprocess_image_for_rows(img):
    # Превръщане в сиво за по-добър контраст
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Изчистване на шума
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    
    # Бинаризация (черно-бяло) за изолиране на текста
    _, thresh = cv2.threshold(denoised, 180, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Премахване на хоризонтални линии, които пречат на четенето по редове[cite: 1]
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    remove_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    cnts = cv2.findContours(remove_horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]
    for c in cnts:
        cv2.drawContours(thresh, [c], -1, (255, 255, 255), 5)
    return thresh

def ocr_pdf(pdf_bytes):
    # Използваме висок DPI за точност при цифрите[cite: 1]
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""

    for i, page in enumerate(pages):
        img = np.array(page)
        processed = preprocess_image_for_rows(img)
        
        # PSM 6 принуждава Tesseract да чете ред по ред[cite: 1]
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(processed, lang="bul+eng", config=custom_config)
        full_text += text + "\n"
    return full_text

# --- 2. ЛОГИКА ЗА ПАРСВАНЕ (ОББ СПЕЦИФИЧНА) ---

def normalize_amount(val):
    if not val: return "0.00"
    # Премахва интервали и превръща запетаи в точки[cite: 1]
    val = val.replace(" ", "").replace(",", ".")
    return val

def parse_statement(text):
    # Извличане на IBAN[cite: 1]
    iban_m = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    iban = iban_m.group(1) if iban_m else "BG00UBBS00000000000000"

    # Извличане на Салда[cite: 1]
    open_bal = re.search(r"Начално салдо\s*:\s*([\d,.]+)", text)
    close_bal = re.search(r"Крайно салдо\s*:\s*([\d,.]+)", text)

    # Разделяне на трансакциите по дата в началото на реда[cite: 1]
    lines = text.split('\n')
    transactions = []
    
    current_tr = None
    
    for line in lines:
        line = line.strip()
        # Търсим формат: ДД/ММ/ГГ (напр. 01/01/26)[cite: 1]
        date_match = re.match(r"^(\d{2}/\d{2}/\d{2,4})", line)
        
        if date_match:
            if current_tr: transactions.append(current_tr)
            
            # Търсим сумата (напр. 3,517.96 EUR)[cite: 1]
            amt_match = re.search(r"([-]?[\d,.]+)\s*EUR", line)
            
            current_tr = {
                "date": date_match.group(1),
                "amount": normalize_amount(amt_match.group(1)) if amt_match else "0.00",
                "desc": line,
                "type": "КРЕДИТ" if amt_match and "-" not in amt_match.group(1) else "ДЕБИТ"
            }
        elif current_tr and line:
            # Добавяме допълнителните редове описание към текущата трансакция[cite: 1]
            current_tr["desc"] += " " + line
            
    if current_tr: transactions.append(current_tr)
    
    return iban, normalize_amount(open_bal.group(1)) if open_bal else "0.00", \
           normalize_amount(close_bal.group(1)) if close_bal else "0.00", transactions

# --- 3. ГЕНЕРИРАНЕ НА XML ---

def generate_xml(iban, open_b, close_b, trs):
    root = ET.Element("STATEMENT")
    ET.SubElement(root, "IBAN").text = iban
    ET.SubElement(root, "OPEN_BALANCE").text = open_b

    for t in trs:
        tr = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tr, "DATE").text = t["date"]
        ET.SubElement(tr, "AMOUNT").text = t["amount"]
        ET.SubElement(tr, "TYPE").text = t["type"]
        ET.SubElement(tr, "DESCRIPTION").text = t["desc"]

    ET.SubElement(root, "CLOSE_BALANCE").text = close_b
    
    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    return xml_str

# --- 4. STREAMLIT ИНТЕРФЕЙС ---

uploaded_file = st.file_uploader("Качете извлечение от ОББ (PDF)", type=["pdf"])

if uploaded_file:
    try:
        with st.spinner("Обработка на документа..."):
            raw_text = ocr_pdf(uploaded_file.read())
        
        st.subheader("Извлечен текст (Row-by-Row)")
        st.text_area("OCR Резултат", raw_text, height=300)
        
        iban, o_bal, c_bal, trs = parse_statement(raw_text)
        
        st.success(f"Намерени {len(trs)} трансакции")
        
        if st.button("Генерирай XML"):
            xml_data = generate_xml(iban, o_bal, c_bal, trs)
            st.code(xml_data, language="xml")
            
            st.download_button(
                label="Свали XML файл",
                data=xml_data,
                file_name="obb_statement.xml",
                mime="text/xml"
            )
            
    except Exception:
        exc_type, exc_value, _ = sys.exc_info()
        st.error(f"Грешка: {exc_value}")
        st.info("Уверете се, че Poppler и Tesseract са инсталирани правилно.")
