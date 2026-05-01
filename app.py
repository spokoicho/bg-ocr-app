import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
import pandas as pd
import os

# ---------------------------------------------------------
# AUTO-DETECT TESSDATA DIR (bul.traineddata)
# ---------------------------------------------------------

POSSIBLE_TESSDATA_DIRS = [
    "/usr/share/tesseract-ocr/4.00/tessdata/",
    "/usr/share/tessdata/",
    "/usr/share/tesseract-ocr/tessdata/",
    "/usr/share/tesseract/tessdata/",
]

def find_tessdata():
    for d in POSSIBLE_TESSDATA_DIRS:
        if os.path.exists(os.path.join(d, "bul.traineddata")):
            return d
    return None

tessdata_dir = find_tessdata()

if tessdata_dir:
    tess_config = f'--tessdata-dir "{tessdata_dir}" --oem 1 --psm 6'
    lang = "bul+eng"
else:
    tess_config = "--oem 1 --psm 6"
    lang = "eng"

pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

# ---------------------------------------------------------
# OCR PREPROCESSING (СТАРИЯТ – по-добрият)
# ---------------------------------------------------------

def clean_text(text):
    text = ''.join(ch for ch in text if 32 <= ord(ch) <= 126 or ch in
                   "абвгдежзийклмнопрстуфхцчшщъьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯ .,:;/()-0123456789")
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

    # morphological closing
    kernel = np.ones((2,2), np.uint8)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)

    # denoise
    th = cv2.fastNlMeansDenoising(th, None, 30, 7, 21)

    return th

# ---------------------------------------------------------
# OCR + RECONSTRUCTION (СТАРИЯТ OCR + НОВАТА РЕКОНСТРУКЦИЯ)
# ---------------------------------------------------------

def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""

    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)

        text = pytesseract.image_to_string(
            processed,
            lang=lang,
            config=tess_config
        )
        full_text += "\n" + text

    cleaned = clean_text(full_text)
    reconstructed = reconstruct_lines(cleaned)
    return reconstructed

# ---------------------------------------------------------
# LINE RECONSTRUCTION — MODE A (от новия скрипт)
# ---------------------------------------------------------

def reconstruct_lines(text: str) -> str:
    text = re.sub(r"(?<!\d)(\d{2}/\d{2}/\d{2})", r"\n\1", text)
    text = re.sub(r"(FT[0-9A-Z]+)", r"\n\1", text)
    text = re.sub(r"(SBD\.[0-9A-Z\-]+)", r"\n\1", text)
    text = re.sub(r"(SBC\.[0-9A-Z\-]+)", r"\n\1", text)
    text = re.sub(r"(8002[0-9A-Z\-]+)", r"\n\1", text)
    text = re.sub(r"([\-]?[0-9.,]+\s*EUR)", r"\n\1", text)
    text = re.sub(r"([\-]?[0-9.,]+\s*BGN)", r"\n\1", text)
    text = re.sub(r"(BGN)([A-ZА-Я])", r"\1\n\2", text)
    text = re.sub(r"(EUR)([A-ZА-Я])", r"\1\n\2", text)

    keywords = [
        "NAP", "DANUK", "ZDRAVNI", "OSIGUROVKI",
        "OT BANKA", "СЧЕТОВОДНИ", "FAKTURA", "ФАКТУРА",
        "ТЕГЛЕНЕ ОТ АТМ", "UBB", "DOGOVOR", "ДОГОВОР",
        "ЕЛЕКТРОТЕХ", "IBEKSA", "HR STUDIO", "ВИОЛИНО",
        "ЕС ПИ ВИ", "0000000111"
    ]
    for kw in keywords:
        text = re.sub(rf"({kw})", r"\n\1", text)

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)

# ---------------------------------------------------------
# PARSER HELPERS (от новия скрипт)
# ---------------------------------------------------------

def normalize_amount(val: str) -> str:
    if not val:
        return ""
    val = val.replace(" ", "").replace(",", ".")
    parts = val.split(".")
    if len(parts) > 2:
        val = "".join(parts[:-1]) + "." + parts[-1]
    return val

def normalize_date(d: str) -> str:
    m = re.match(r"(\d{2})/(\d{2})/(\d{2,4})", d)
    if not m:
        return d
    dd, mm, yy = m.groups()
    if len(yy) == 2:
        yy = "20" + yy
    return f"{dd}/{mm}/{yy}"

def is_outgoing(block: str, amount: str) -> bool:
    b = block.upper()
    if "-" in amount:
        return True
    if "ТЕГЛЕНЕ" in b or "ATM" in b:
        return True
    if "ИЗХОДЯЩ" in b:
        return True
    if "FT" in b and "ПОЛУЧЕН" not in b:
        return True
    return False

def detect_type(block: str, outgoing: bool) -> str:
    b = block.upper()
    if "SBD" in b and not outgoing:
        return "СЕПА ПОЛУЧЕН"
    if "SBC" in b or ("SBD" in b and outgoing):
        return "СЕПА ИЗХОДЯЩ"
    if "ТЕГЛЕНЕ" in b or "ATM" in b:
        return "ATM ТЕГЛЕНЕ"
    if "ТАКСА" in b:
        return "ТАКСА ОБСЛУЖВАНЕ"
    return "ПРЕВОД"

def extract_reference(block: str) -> str:
    m = re.search(r"(FT[0-9A-Z]+|SBD\.[0-9A-Z\-]+|SBC\.[0-9A-Z\-]+|8002[0-9A-Z\-]+)", block)
    return m.group(1) if m else ""

def extract_name_r(lines, idx: int) -> str:
    for i in range(idx+1, len(lines)):
        t = lines[i].strip()
        if any(x in t for x in ["EUR", "BGN"]):
            continue
        if re.match(r"\d{2}/\d{2}/\d{2}", t):
            continue
        if re.match(r"(FT|SBD|SBC)", t):
            continue
        if "OT BANKA" in t.upper():
            continue
        if len(t.split()) <= 6:
            return t
    return ""

def extract_rem_i(lines, idx: int, name_r: str) -> str:
    start = False
    for i in range(idx+1, len(lines)):
        t = lines[i].strip()
        if t == name_r:
            start = True
            continue
        if start and any(k in t.upper() for k in ["ФАКТ", "FAKT", "УСЛУГ", "НОМЕР"]):
            return t
    return ""

def extract_rem_ii(block: str) -> str:
    m = re.findall(r"\b[0-9A-Z]{10,30}\b", block)
    return m[-1] if m else ""

# ---------------------------------------------------------
# MAIN PARSER (от новия скрипт)
# ---------------------------------------------------------

def parse_statement(text: str):
    lines = [l for l in text.split("\n") if l.strip()]
    transactions = []

    for i, line in enumerate(lines):
        if re.match(r"^\d{2}/\d{2}/\d{2}", line):
            block = line
            j = i + 1
            while j < len(lines) and not re.match(r"^\d{2}/\d{2}/\d{2}", lines[j]):
                block += "\n" + lines[j]
                j += 1

            date = normalize_date(line.split()[0])
            amt_m = re.search(r"([\-]?[0-9.,]+)\s*EUR", block)
            amount = normalize_amount(amt_m.group(1)) if amt_m else ""

            outgoing = is_outgoing(block, amount)
            tr_type = detect_type(block, outgoing)
            reference = extract_reference(block)
            name_r = extract_name_r(lines, i)
            rem_i = extract_rem_i(lines, i, name_r)
            rem_ii = extract_rem_ii(block)

            transactions.append({
                "date": date,
                "amount": amount,
                "type": tr_type,
                "name_r": name_r,
                "rem_i": rem_i,
                "rem_ii": rem_ii,
                "reference": reference,
                "outgoing": outgoing
            })

    return transactions

# ---------------------------------------------------------
# XML GENERATOR (от новия скрипт)
# ---------------------------------------------------------

def generate_xml(iban: str, transactions):
    root = ET.Element("STATEMENT")
    ET.SubElement(root, "IBAN_S").text = iban

    for t in transactions:
        tr = ET.SubElement(root, "TRANSACTION")
        ET.SubElement(tr, "POST_DATE").text = t["date"]

        if t["outgoing"]:
            ET.SubElement(tr, "AMOUNT_D").text = t["amount"]
        else:
            ET.SubElement(tr, "AMOUNT_C").text = t["amount"]

        ET.SubElement(tr, "TR_NAME").text = t["type"]
        ET.SubElement(tr, "NAME_R").text = t["name_r"]
        ET.SubElement(tr, "REM_I").text = t["rem_i"]
        ET.SubElement(tr, "REM_II").text = t["rem_ii"]
        ET.SubElement(tr, "REFERENCE").text = t["reference"]

    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    xml_str = xml_str.replace("><", ">\n<")
    return xml_str

# ---------------------------------------------------------
# STREAMLIT UI (от новия скрипт)
# ---------------------------------------------------------

st.title("PDF → XML (ОББ формат) — Комбиниран OCR (най-добър вариант)")

uploaded = st.file_uploader("Качи PDF", type=["pdf"])

if uploaded:
    text = ocr_pdf(uploaded.read())

    st.subheader("OCR текст (ред по ред)")
    st.text_area("OCR", text, height=400)

    trs = parse_statement(text)

    st.subheader("Визуален преглед на транзакциите")

    df = pd.DataFrame([
        {
            "Дата": t["date"],
            "Вид": t["type"],
            "Наредител/Получател": t["name_r"],
            "Основание": t["rem_i"],
            "Сума": t["amount"],
            "Тип": "Кредит" if not t["outgoing"] else "Дебит"
        }
        for t in trs
    ])

    st.dataframe(df, use_container_width=True)

    iban = st.text_input("IBAN", "BG21UBBS80021081570250")

    if st.button("Генерирай XML"):
        xml_output = generate_xml(iban, trs)
        st.code(xml_output, language="xml")
        st.download_button(
            "Свали XML",
            data=xml_output.encode("utf-8"),
            file_name="statement.xml",
            mime="application/xml"
        )
