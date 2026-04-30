import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
from io import BytesIO

# -----------------------------
# OCR PREPROCESSING
# -----------------------------

def clean_text(text):
    # премахване на wide unicode символи
    text = ''.join(ch for ch in text if 32 <= ord(ch) <= 126 or ch in "абвгдежзийклмнопрстуфхцчшщъьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯ .,:;/()-0123456789")
    # премахване на control chars
    text = re.sub(r'[\x00-\x1F\x7F]', '', text)
    return text

def preprocess_image(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # deskew
    coords = np.column_stack(np.where(gray < 255))
    if len(coords) > 0:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        (h, w) = gray.shape[:2]
        M = cv2.getRotationMatrix2D((w//2, h//2), angle, 1.0)
        gray = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC)

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)

    # adaptive threshold
    th = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY,31,15)

    # denoise
    th = cv2.fastNlMeansDenoising(th, None, 30, 7, 21)

    return th

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""

    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        text = pytesseract.image_to_string(processed, lang="bul+eng", config="--oem 1 --psm 4")
        full_text += "\n" + text

    return clean_text(full_text)

# -----------------------------
# PARSER HELPERS
# -----------------------------

def normalize_amount(val):
    if not val:
        return ""
    val = val.replace(" ", "")
    val = val.replace(",", ".")
    # премахване на всички точки освен последната
    parts = val.split(".")
    if len(parts) > 2:
        val = "".join(parts[:-1]) + "." + parts[-1]
    return val

def detect_type(line):
    line = line.upper()
    if "SBD" in line:
        return "СЕПА ПОЛУЧЕН"
    if "SBC" in line:
        return "СЕПА ИЗХОДЯЩ"
    if "ATM" in line or "ТЕГЛЕНЕ" in line:
        return "ATM ТЕГЛЕНЕ"
    if "POS" in line:
        return "POS ПЛАЩАНЕ"
    if "TAKSA" in line or "ТАКСА" in line:
        return "ТАКСА ОБСЛУЖВАНЕ"
    if "PREVAL" in line or "ПРЕВАЛУТ" in line:
        return "ПРЕВАЛУТИРАНЕ"
    if "FT" in line:
        return "ПРЕВОД"
    return "ПРЕВОД"

def extract_rem(text):
    # REM_I = човешко описание
    # REM_II = технически идентификатор
    rem_i = ""
    rem_ii = ""

    # фактура / договор / документ
    m = re.search(r"(ФАКТУРА[^ \n]*.*|ДОГОВОР[^ \n]*.*|ДОКУМЕНТ[^ \n]*.*|Ф\s*\d+)", text, re.IGNORECASE)
    if m:
        rem_i = m.group(0).strip()

    # технически кодове
    m2 = re.findall(r"\b[0-9A-Z]{12,20}\b", text)
    if m2:
        rem_ii = m2[-1]

    return rem_i, rem_ii

def extract_name_r(text):
    m = re.search(r"ОТ БАНКА[: ]+([A-Za-z0-9 .\-()]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""

# -----------------------------
# MAIN PARSER
# -----------------------------

def parse_statement(text):
    lines = text.split("\n")

    # период
    m = re.search(r"ОТ\s+(\d{2}\/\d{2}\/\d{4}).*ДО\s+(\d{2}\/\d{2}\/\d{4})", text)
    from_date = m.group(1) if m else ""
    till_date = m.group(2) if m else ""

    # салда
    m2 = re.search(r"Начално салдо[: ]+([0-9.,]+)", text)
    open_balance = normalize_amount(m2.group(1)) if m2 else ""

    m3 = re.search(r"Крайно салдо[: ]+([0-9.,]+)", text)
    close_balance = normalize_amount(m3.group(1)) if m3 else ""

    # транзакции
    transactions = []
    current = []

    for line in lines:
        if re.search(r"\d{2}\/\d{2}\/\d{4}", line):
            if current:
                transactions.append("\n".join(current))
                current = []
        current.append(line)

    if current:
        transactions.append("\n".join(current))

    parsed = []

    for block in transactions:
        date_m = re.search(r"(\d{2}\/\d{2}\/\d{4})", block)
        if not date_m:
            continue
        date = date_m.group(1)

        amt_m = re.search(r"([\-]?[0-9.,]+)\s*EUR", block)
        amount = normalize_amount(amt_m.group(1)) if amt_m else ""

        tr_type = detect_type(block)
        name_r = extract_name_r(block)
        rem_i, rem_ii = extract_rem(block)

        ref_m = re.search(r"(FT[0-9A-Z]+|SBD\.[0-9\-A-Z]+|SBC\.[0-9\-A-Z]+)", block)
        reference = ref_m.group(1) if ref_m else ""

        parsed.append({
            "date": date,
            "amount": amount,
            "type": tr_type,
            "name_r": name_r,
            "rem_i": rem_i,
            "rem_ii": rem_ii,
            "reference": reference
        })

    return from_date, till_date, open_balance, close_balance, parsed

# -----------------------------
# XML GENERATOR (ОББ FORMAT)
# -----------------------------

def generate_xml(iban, from_date, till_date, open_balance, close_balance, transactions):
    root = ET.Element("STATEMENT")

    ET.SubElement(root, "IBAN_S").text = iban
    ET.SubElement(root, "FROM_ST_DATE").text = from_date
    ET.SubElement(root, "TILL_ST_DATE").text = till_date
    ET.SubElement(root, "OPEN_BALANCE").text = open_balance

    for t in transactions:
        tr = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tr, "POST_DATE").text = t["date"]

        # кредит или дебит
        if t["type"] in ["СЕПА ПОЛУЧЕН", "ATM ТЕГЛЕНЕ", "POS ПЛАЩАНЕ", "ПРЕВАЛУТИРАНЕ", "ПРЕВОД"]:
            ET.SubElement(tr, "AMOUNT_C").text = t["amount"]
        else:
            ET.SubElement(tr, "AMOUNT_D").text = t["amount"]

        ET.SubElement(tr, "TR_NAME").text = t["type"]
        ET.SubElement(tr, "NAME_R").text = t["name_r"]
        ET.SubElement(tr, "REM_I").text = t["rem_i"]
        ET.SubElement(tr, "REM_II").text = t["rem_ii"]
        ET.SubElement(tr, "REFERENCE").text = t["reference"]

    ET.SubElement(root, "CLOSE_BALANCE").text = close_balance

    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    xml_str = xml_str.replace("><", ">\n<")  # всеки елемент на нов ред
    return xml_str

# -----------------------------
# STREAMLIT UI
# -----------------------------

st.title("PDF → XML (ОББ формат)")

uploaded = st.file_uploader("Качи PDF", type=["pdf"])

if uploaded:
    text = ocr_pdf(uploaded.read())
    st.text_area("OCR TEXT", text, height=400)
    iban = st.text_input("IBAN", "BG00XXXX00000000000000")

    if st.button("Генерирай XML"):
        from_d, till_d, open_b, close_b, trs = parse_statement(text)
        xml_output = generate_xml(iban, from_d, till_d, open_b, close_b, trs)

        st.code(xml_output, language="xml")

        st.download_button(
            "Свали XML",
            data=xml_output.encode("utf-8"),
            file_name="statement.xml",
            mime="application/xml"
        )
