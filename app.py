import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from io import BytesIO
import PyPDF2
from pdfminer.high_level import extract_text

from name_fixes import init_db, get_fixes, save_single_fix

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="Statement Converter", layout="wide")
init_db()

# ---------------------------------------------------------
# DATE NORMALIZATION
# ---------------------------------------------------------
def normalize_date(date_str):
    date_str = date_str.replace(".", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(date_str, fmt)
            return d.strftime("%d/%m/%Y")
        except:
            pass
    return date_str

# ---------------------------------------------------------
# PDF TYPE CHECK
# ---------------------------------------------------------
def is_scanned_pdf(pdf_bytes):
    try:
        reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        first_page = reader.pages[0]
        text = first_page.extract_text()
        return text is None or text.strip() == ""
    except:
        return True

# ---------------------------------------------------------
# DIRECT TEXT EXTRACTION (NO OCR)
# ---------------------------------------------------------
def extract_pdf_text(pdf_bytes):
    try:
        return extract_text(BytesIO(pdf_bytes))
    except:
        return ""

# ---------------------------------------------------------
# OCR FOR SCANNED PDF
# ---------------------------------------------------------
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
        text = pytesseract.image_to_string(processed, lang="bul+eng", config="--oem 3 --psm 6")
        full_text += text + "\n"
    return full_text

# ---------------------------------------------------------
# HYBRID PDF TEXT EXTRACTOR
# ---------------------------------------------------------
def get_pdf_text(pdf_bytes):
    # 1) Direct extraction
    try:
        text = extract_text(BytesIO(pdf_bytes))
        if text and len(text.strip()) > 200:
            return text
    except:
        pass

    # 2) OCR fallback
    return ocr_pdf(pdf_bytes)

# ---------------------------------------------------------
# APPLY FIXES
# ---------------------------------------------------------
def apply_fixes(text):
    fixes = get_fixes()
    for original, corrected in fixes:
        text = text.replace(original, corrected)
    return text

# ---------------------------------------------------------
# UNICREDIT NAME + REASON EXTRACTION
# ---------------------------------------------------------
def extract_name_and_reason(desc):
    # Нормализиране на интервали и нови редове
    clean = re.sub(r"\s+", " ", desc).strip()

    # 1) ATM / карта
    if re.search(r"\bATM\b", clean, re.IGNORECASE) or "Операция с карта" in clean:
        return "null", "ТЕГЛЕНЕ АТМ"

    # 2) Контрагент:
    m = re.search(r"Контрагент\s*:?\s*([A-ZА-Я0-9\s\.\-]+)", clean)
    if m:
        name = m.group(1).strip()
        # Основание след "Основание:"
        rem_match = re.search(r"Основание\s*:?\s*(.+)$", clean)
        rem = rem_match.group(1).strip() if rem_match else clean
        return name, rem

    # 3) IBAN + име след него
    m = re.search(r"(BG\d{20})\s*/\s*([A-ZА-Я0-9\s\.\-]+)", clean)
    if m:
        name = m.group(2).strip()
        # Основание след "Основание:"
        rem_match = re.search(r"Основание\s*:?\s*(.+)$", clean)
        rem = rem_match.group(1).strip() if rem_match else clean
        return name, rem

    # 4) Само основание
    m = re.search(r"Основание\s*:?\s*(.+)$", clean)
    if m:
        return "null", m.group(1).strip()

    # 5) fallback – цялото описание като основание
    return "null", clean

# ---------------------------------------------------------
# UNICREDIT PARSER (FINAL)
# ---------------------------------------------------------
def parse_unicredit_statement(text):
    # Почистване на текста от повтарящи се хедъри на страници
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    clean_lines = []
    for l in lines:
        if "Извлечение | Statement" in l or "№ 4/" in l or "Страница" in l:
            continue
        clean_lines.append(l)

    # Извличане на IBAN
    iban_match = re.search(r"IBAN\s*[:\s]*(BG\d{2}UNCR\d{14})", text)
    iban = iban_match.group(1) if iban_match else "Неизвестен"

    # Групиране в блокове по дата[cite: 1]
    blocks = []
    current_block = []
    for line in clean_lines:
        if re.match(r"^\d{2}\.\d{2}\.\d{4}", line):
            if current_block:
                blocks.append("\n".join(current_block))
            current_block = [line]
        else:
            if current_block:
                current_block.append(line)
    if current_block:
        blocks.append("\n".join(current_block))

    transactions = []
    for block in blocks:
        # 1. Намиране на дата
        date_m = re.search(r"(\d{2}\.\d{2}\.\d{4})", block)
        if not date_m: continue
        
        # 2. Намиране на сума и тип (дт/кт)[cite: 1, 2]
        # Изразът поддържа суми с интервали като "1 000.00"
        amt_type_m = re.search(r"([\d\s,]+\.\d{2})\s*(дт|кт|DT|KT|CT|KT)", block, re.IGNORECASE)
        
        if amt_type_m:
            raw_amt = amt_type_m.group(1).replace(" ", "").replace(",", "")
            raw_type = amt_type_m.group(2).upper()
            
            amt = f"{float(raw_amt):.2f}"
            tr_type = "D" if raw_type in ("ДТ", "DT") else "C"
            
            # 3. Почистване на описанието[cite: 2]
            desc = block.replace(date_m.group(0), "").replace(amt_type_m.group(0), "")
            desc = " ".join(desc.replace("|", "").split())

            name, rem = extract_name_and_reason(desc)

            # 4. АТМ Логика
            if "ATM" in desc or "Операция с карта" in desc:
                name = "null"
                rem = "ТЕГЛЕНЕ АТМ"
                tr_name = "ТЕГЛЕНЕ"
            else:
                tr_name = "ОПЕРАЦИЯ"

            transactions.append({
                "post_date": normalize_date(date_m.group(0)),
                "name": name[:50],
                "rem1": rem[:100],
                "tr_name": tr_name,
                "amt": amt,
                "type": tr_type,
            })

    return iban, transactions

# ---------------------------------------------------------
# UI СТРУКТУРА
# ---------------------------------------------------------
st.title("🏦 Конвертор UniCredit (Блоков режим)")

uploaded_file = st.file_uploader("Качете PDF извлечение", type="pdf")

if uploaded_file:
    with st.spinner("Анализиране на блокове..."):
        pdf_bytes = uploaded_file.read()
        # Извличане на текста
        text = extract_text(BytesIO(pdf_bytes))
        
        iban, trs = parse_unicredit_statement(text)
        
        if trs:
            st.success(f"Намерени са {len(trs)} трансакции за IBAN: {iban}")
            df = pd.DataFrame(trs)
            st.data_editor(df, use_container_width=True, hide_index=True)
            
            # Бутон за XML (примерна структура)
            if st.button("Подготви XML за изтегляне"):
                st.info("XML генерирането е готово.")
        else:
            st.error("Трансакциите не бяха открити. Текстът в PDF-а може да е защитен или нечетим.")
            st.text_area("Извлечен текст (за диагностика):", text[:1000], height=200)
# ---------------------------------------------------------
# OBB PARSER
# ---------------------------------------------------------
def parse_obb_statement(text):
    iban_match = re.search(r"IBAN\s*:\s*(BG\d{2}UBBS\d{14})", text)
    iban = iban_match.group(1) if iban_match else "Неизвестен"

    transactions = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        date_match = re.match(r"^(\d{2}/\d{2}/\d{2,4})", line)
        if date_match:
            raw_date = date_match.group(1)
            fixed_date = normalize_date(raw_date)

            tr = {
                "post_date": fixed_date,
                "name": "null",
                "rem1": "null",
                "tr_name": "ОПЕРАЦИЯ",
                "amt": "0.00",
                "type": "C",
            }

            amt_match = re.search(r"(-?[\d\s,]+\.\d{2})\s*EUR", line.replace(",", ""))
            if amt_match:
                val_str = amt_match.group(1).replace(" ", "")
                val_float = float(val_str)
                tr["amt"] = f"{abs(val_float):.2f}"
                tr["type"] = "D" if val_float < 0 else "C"

            curr_j = i + 1
            extra_info = []
            while curr_j < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2}", lines[curr_j]):
                extra_info.append(lines[curr_j])
                curr_j += 1

            if len(extra_info) >= 1:
                tr["name"] = extra_info[0]
            if len(extra_info) >= 2:
                tr["rem1"] = extra_info[1]

            transactions.append(tr)
            i = curr_j - 1
        i += 1

    return iban, "Клиент", transactions

# ---------------------------------------------------------
# XML GENERATION
# ---------------------------------------------------------
def generate_xml(iban, trs):
    root = ET.Element("STATEMENT")
    ET.SubElement(root, "IBAN_S").text = iban

    for t in trs:
        tran = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tran, "POST_DATE").text = t["post_date"]
        tag = "AMOUNT_C" if t["type"] == "C" else "AMOUNT_D"
        ET.SubElement(tran, tag).text = t["amt"]
        ET.SubElement(tran, "TR_NAME").text = t["tr_name"]
        ET.SubElement(tran, "NAME_R").text = t["name"]
        ET.SubElement(tran, "REM_I").text = t["rem1"]

    xml_str = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(xml_str).toprettyxml(indent="  ")

# ---------------------------------------------------------
# UI
# ---------------------------------------------------------
st.title("🏦 Конвертор на банкови извлечения (ОББ + UniCredit)")

file = st.file_uploader("Качете PDF", type="pdf")

if file:
    with st.spinner("Обработка..."):
        pdf_bytes = file.read()

        text = get_pdf_text(pdf_bytes)
        text = apply_fixes(text)

        if "UniCredit Bulbank" in text or "УниКредит Булбанк" in text:
            bank = "UniCredit"
            iban, client_name, transactions = parse_unicredit_statement(text)
        else:
            bank = "OBB"
            iban, client_name, transactions = parse_obb_statement(text)

        if transactions:
            df = pd.DataFrame(transactions)

            st.subheader("✏️ Редактирайте имена и основания")
            edited_df = st.data_editor(
                df[["post_date", "name", "rem1", "tr_name", "amt", "type"]],
                use_container_width=True,
                hide_index=True,
            )

            if st.button("💾 Запази всички корекции"):
                fixes = []
                for original, corrected in zip(df["name"], edited_df["name"]):
                    if original != corrected:
                        fixes.append([original, corrected])
                for original, corrected in zip(df["rem1"], edited_df["rem1"]):
                    if original != corrected:
                        fixes.append([original, corrected])

                for original, corrected in fixes:
                    save_single_fix(original, corrected)

                st.success("Корекциите са запазени!")
                transactions = edited_df.to_dict(orient="records")

            xml_data = generate_xml(iban, transactions)

            first_date = transactions[0]["post_date"]
            year = first_date[6:10]
            month = first_date[3:5]

            xml_filename = f"{bank}-{client_name}-{year}-{month}.xml"
            xml_filename = xml_filename.replace(" ", "_")

            st.download_button(
                label="📥 Изтегли XML",
                data=xml_data,
                file_name=xml_filename,
                mime="text/xml",
            )
        else:
            st.error("Не са открити трансакции.")
