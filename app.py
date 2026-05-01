import streamlit as st
import pytesseract
from pdf2image import convert_from_bytes
import cv2
import numpy as np
import re
import xml.etree.ElementTree as ET
import pandas as pd

# ---------------------------------------------------------
# OCR PREPROCESSING (preserve line structure)
# ---------------------------------------------------------

def clean_text(text):
    text = ''.join(ch for ch in text if 32 <= ord(ch) <= 126 or ch in
                   "абвгдежзийклмнопрстуфхцчшщъьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯ .,:;/()-0123456789")
    text = re.sub(r'[\x00-\x1F\x7F]', '', text)
    return text


def preprocess_image(img):
    # Preserve lines — no adaptive threshold, no morphology
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3,3), 0)
    gray = cv2.equalizeHist(gray)
    return gray


def fix_lines(text):
    # New line before date
    text = re.sub(r"(?<!\d)(\d{2}/\d{2}/\d{2})", r"\n\1", text)

    # New line before FT/SBD/SBC
    text = re.sub(r"(FT[0-9A-Z]+)", r"\n\1", text)
    text = re.sub(r"(SBD\.[0-9A-Z\-]+)", r"\n\1", text)
    text = re.sub(r"(SBC\.[0-9A-Z\-]+)", r"\n\1", text)

    # New line before EUR/BGN
    text = re.sub(r"([0-9.,]+\s*EUR)", r"\n\1", text)
    text = re.sub(r"([0-9.,]+\s*BGN)", r"\n\1", text)

    # Remove double spaces
    text = re.sub(r"[ ]{2,}", " ", text)

    # Remove empty lines
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)


def ocr_pdf(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes, dpi=400)
    full_text = ""

    for page in pages:
        img = np.array(page)
        processed = preprocess_image(img)
        raw = pytesseract.image_to_string(
            processed,
            lang="bul+eng",
            config="--oem 1 --psm 4"   # preserve line structure
        )
        full_text += "\n" + raw

    return fix_lines(clean_text(full_text))


# ---------------------------------------------------------
# PARSER HELPERS
# ---------------------------------------------------------

def normalize_amount(val):
    if not val:
        return ""
    val = val.replace(" ", "").replace(",", ".")
    parts = val.split(".")
    if len(parts) > 2:
        val = "".join(parts[:-1]) + "." + parts[-1]
    return val


def normalize_date(d):
    m = re.match(r"(\d{2})/(\d{2})/(\d{2,4})", d)
    if not m:
        return d
    dd, mm, yy = m.groups()
    if len(yy) == 2:
        yy = "20" + yy
    return f"{dd}/{mm}/{yy}"


def is_outgoing(block, amount):
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


def detect_type(block, outgoing):
    b = block.upper()
    if "SBD" in b and not outgoing:
        return "СЕПА ПОЛУЧЕН"
    if "SBC" in b or ("SBD" in b and outgoing):
        return "СЕПА ИЗХОДЯЩ"
    if "ТЕГЛЕНЕ" in b or "ATM" in b:
        return "ATM ТЕГЛЕНЕ"
    if "TAKSA" in b or "ТАКСА" in b:
        return "ТАКСА ОБСЛУЖВАНЕ"
    return "ПРЕВОД"


def extract_reference(block):
    m = re.search(r"(FT[0-9A-Z]+|SBD\.[0-9A-Z\-]+|SBC\.[0-9A-Z\-]+|8002[0-9A-Z\-]+)", block)
    return m.group(1) if m else ""


def extract_name_r(lines, idx):
    for i in range(idx+1, len(lines)):
        t = lines[i].strip()
        if any(x in t for x in ["EUR", "BGN"]):
            continue
        if re.match(r"\d{2}/\d{2}/\d{2,4}", t):
            continue
        if re.match(r"(FT|SBD|SBC)\.", t):
            continue
        if "OT BANKA" in t.upper():
            continue
        if "ПОЛУЧЕН" in t.upper() or "ПРЕВОД" in t.upper():
            continue
        if len(t.split()) <= 6:
            return t
    return ""


def extract_rem_i(lines, idx, name_r):
    start = False
    for i in range(idx+1, len(lines)):
        t = lines[i].strip()
        if t == name_r:
            start = True
            continue
        if start:
            if any(k in t.upper() for k in ["ФАКТ", "FAKT", "ДОКУМ", "DOC", "УСЛУГ", "TRANSFER", "НОМЕР"]):
                return t
    return ""


def extract_rem_ii(block):
    m = re.findall(r"\b[0-9A-Z]{10,30}\b", block)
    if m:
        return m[-1]
    return ""


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_statement(text):

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
# XML GENERATOR
# ---------------------------------------------------------

def generate_xml(iban, transactions):
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
# STREAMLIT UI
# ---------------------------------------------------------

st.title("PDF → XML (ОББ формат)")

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

    st.dataframe(
        df.style.format({"Сума": lambda x: f"{x} EUR"}).apply(
            lambda row: ["color: green" if row["Тип"] == "Кредит" else "color: red"] * len(row),
            axis=1
        ),
        use_container_width=True
    )

    iban = st.text_input("IBAN", "BG00XXXX00000000000000")

    if st.button("Генерирай XML"):
        xml_output = generate_xml(iban, trs)

        st.code(xml_output, language="xml")

        st.download_button(
            "Свали XML",
            data=xml_output.encode("utf-8"),
            file_name="statement.xml",
            mime="application/xml"
        )
