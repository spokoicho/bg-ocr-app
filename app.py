import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import sys

def preprocess_image_for_rows(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, thresh = cv2.threshold(denoised, 180, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""
    for page in pages:
        img = np.array(page)
        processed = preprocess_image_for_rows(img)
        # Използваме psm 6 за запазване на структурата по редове[cite: 1]
        text = pytesseract.image_to_string(processed, lang="bul+eng", config='--oem 3 --psm 6')
        full_text += text + "\n"
    
    # Корекция на често срещани OCR грешки[cite: 2, 3]
    full_text = full_text.replace("CENA", "СЕПА").replace("580.", "SBD.")
    return full_text

def parse_obb_statement(text):
    # Извличане на метаданни
    iban = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    dates = re.findall(r"(\d{2})\s+(ЯНУ|ФЕВ|МАР|АПР|МАЙ|ЮНИ|ЮЛИ|АВГ|СЕП|ОКТ|НОЕ|ДЕК)\s+(\d{4})", text)
    
    transactions = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    i = 0
    while i < len(lines):
        line = lines[i]
        # Търсим начало на трансакция (Дата Вальор Референция)
        match = re.match(r"^(\d{2}/\d{2}/\d{2,4})\s+(\d{2}/\d{2})", line)
        
        if match:
            tr = {"post_date": match.group(1), "ref": "", "name": "", "rem1": "", "rem2": "", "type": "", "amt": ""}
            
            # Извличане на сума и референция от основния ред[cite: 2, 5]
            amt_match = re.search(r"(-?[\d,.]+)\s*EUR", line)
            if amt_match:
                val = amt_match.group(1).replace(",", "")
                tr["amt"] = val.replace("-", "")
                tr["type"] = "D" if "-" in val else "C"
            
            ref_match = re.search(r"(FT\w+|SBD\.\d+-\d+-\d+-\d+-\d+|8002\d+-\d+)", line)
            if ref_match: tr["ref"] = ref_match.group(1)
            
            # Опит за извличане на име на трансакция (напр. МЕСЕЧНА ТАКСА)
            tr_name_match = re.search(r"(?:СЕПА ПОЛУЧЕН|ИЗХОДЯЩ ПРЕВОД СЕПА|МЕСЕЧНА ТАКСА|ТЕГЛЕНЕ ОТ АТМ|ТАКСА ОБСЛУЖВАНЕ|ПРЕВАЛУТИРАНЕ)", line)
            tr["tr_name"] = tr_name_match.group(0) if tr_name_match else ""

            # Проверка на следващите редове за Име на контрагент и Описание[cite: 2, 5]
            if i + 1 < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2}", lines[i+1]):
                tr["name"] = lines[i+1]
                if i + 2 < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2}", lines[i+2]):
                    tr["rem1"] = lines[i+2]
                if i + 3 < len(lines) and "ОТ БАНКА" in lines[i+3]:
                    tr["rem2"] = lines[i+3]
            
            transactions.append(tr)
        i += 1
        
    return iban.group(1) if iban else "", transactions

def generate_xml_final(iban, trs):
    root = ET.Element("STATEMENT")
    if iban: ET.SubElement(root, "IBAN_S").text = iban
    
    for t in trs:
        tran = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tran, "POST_DATE").text = t["post_date"]
        ET.SubElement(tran, "AMOUNT_C" if t["type"] == "C" else "AMOUNT_D").text = t["amt"]
        ET.SubElement(tran, "TR_NAME").text = t["tr_name"]
        ET.SubElement(tran, "NAME_R").text = t["name"]
        ET.SubElement(tran, "REM_I").text = t["rem1"]
        ET.SubElement(tran, "REM_II").text = t["rem2"]
        ET.SubElement(tran, "REFERENCE").text = t["ref"]

    xml_str = ET.tostring(root, encoding="utf-8")
    parsed_xml = minidom.parseString(xml_str)
    return parsed_xml.toprettyxml(indent="  ")

# --- Streamlit UI ---
uploaded_file = st.file_uploader("Качете ОББ PDF", type="pdf")
if uploaded_file:
    raw_text = ocr_pdf(uploaded_file.read())
    iban, transactions = parse_obb_statement(raw_text)
    final_xml = generate_xml_final(iban, transactions)
    
    st.download_button("Свали коригиран XML", final_xml, "statement_final.xml", "text/xml")
    st.code(final_xml, language="xml")
