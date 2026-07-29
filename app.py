import io
import re
import json
import pandas as pd
import pikepdf
import pdfplumber
import streamlit as st
from pikepdf import PasswordError
from datetime import datetime
# --- สำหรับ Gemini ---
from google import genai
from google.genai import types
import os
import unicodedata

# ตั้งค่าหน้าเว็บ Streamlit
st.set_page_config(page_title="PDF Statement Converter", layout="wide")

# ================= 0. AI Configuration =================
GEMINI_API_KEY_V1 = st.secrets["GEMINI_API_KEY_V1"]
client = genai.Client(api_key=GEMINI_API_KEY_V1)

def process_bay_with_gemini(file_bytes, password):
    """ฟังก์ชันจัดการไฟล์ BAY ด้วย Gemini AI"""
    unlocked_bytes = file_bytes
    try:
        with pikepdf.open(io.BytesIO(file_bytes), password=password) as pdf:
            out_pdf = io.BytesIO()
            pdf.save(out_pdf)
            unlocked_bytes = out_pdf.getvalue()
    except:
        pass

    model_name = "gemini-1.5-flash" 
    prompt = """
    คุณคือ OCR ผู้เชี่ยวชาญด้านบัญชี โปรดอ่านสเตทเมนท์ธนาคารกรุงศรี (BAY) จากไฟล์นี้
    และคืนค่าเป็น JSON Array ของ Array เท่านั้น [["วันที่", "เวลา", "จำนวนเงิน", "ยอดคงเหลือ", "รหัส", "รายละเอียด", "ช่องทาง", "รหัสสาขา"]]
    กฎเหล็ก:
    1. คอลัมน์ 'จำนวนเงิน': หากเป็นการ 'ถอน' ให้ติดลบ หากเป็น 'ฝาก' ให้เป็นบวก
    2. วันที่และเวลา: แยกออกจากกัน
    3. รายละเอียด: รวมข้อความคำอธิบายทั้งหมดให้อยู่ในบรรทัดเดียวกัน
    4. ห้ามมี Header ในข้อมูลที่ส่งกลับมา
    5. คืนค่าเฉพาะ JSON ห้ามมีคำอธิบายอื่น
    """
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[types.Part.from_bytes(data=unlocked_bytes, mime_type="application/pdf"), prompt],
            config=types.GenerateContentConfig(response_mime_type='application/json'),
        )
        res_text = response.text.strip()
        if res_text.startswith("```"):
            res_text = res_text.replace("```json", "").replace("```", "").strip()
        return json.loads(res_text)
    except Exception as e:
        st.error(f"Gemini Error (BAY): {str(e)}")
        return None

def process_ktb_scan_with_gemini(file_bytes, mime_type):
    """ฟังก์ชันใหม่: จัดการไฟล์ KTB (Scan/Picture) ด้วย AI"""
    model_name = "gemini-1.5-flash" 
    prompt = """
    คุณคือ OCR ผู้เชี่ยวชาญด้านบัญชี โปรดอ่านสเตทเมนท์ธนาคารกรุงไทย (KTB) จากไฟล์นี้
    และคืนค่าเป็น JSON Array ของ Array เท่านั้น [["วันที่", "เวลา", "รายการ", "จำนวนเงิน", "ยอดคงเหลือ", "รายละเอียด"]]
    กฎเหล็กสำหรับกรุงไทย:
    1. ตรวจสอบคอลัมน์ 'ถอนเงิน' และ 'ฝากเงิน': 
       - หากมีตัวเลขในช่อง 'ถอนเงิน' ให้คืนค่าเป็นเลขติดลบ (เช่น -250.00)
       - หากมีตัวเลขในช่อง 'ฝากเงิน' ให้คืนค่าเป็นเลขบวก (เช่น 500.00)
       - ห้ามใส่เครื่องหมายคอมมา (,) ในตัวเลข
    2. วันที่: ใช้รูปแบบ DD/MM/YY
    3. รายละเอียด: รวมข้อความคำอธิบายทั้งหมดให้อยู่ในบรรทัดเดียวกัน
    4. คืนค่าเฉพาะ JSON ห้ามมีคำอธิบายอื่น
    """
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt],
            config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.1),
        )
        res_text = response.text.strip()
        if res_text.startswith("```"):
            res_text = res_text.replace("```json", "").replace("```", "").strip()
        return json.loads(res_text)
    except Exception as e:
        st.error(f"Gemini Error (KTB Scan): {str(e)}")
        return None

# ================= 1. ฟังก์ชันช่วยเหลือทั่วไป (คงเดิม) =================
def str_to_float(val_str):
    if not val_str or str(val_str).strip() in ["", "-", "None"]: return 0.0
    try:
        clean_val = re.sub(r'[^\d.-]', '', str(val_str))
        return float(clean_val)
    except:
        return 0.0

def decode_cid(text):
    if not text: return ""
    cid_map = {"(cid:344)": "0", "(cid:345)": "1", "(cid:346)": "2", "(cid:347)": "3", "(cid:348)": "4",
               "(cid:349)": "5", "(cid:350)": "6", "(cid:351)": "7", "(cid:352)": "8", "(cid:353)": "9"}
    for cid, val in cid_map.items(): text = text.replace(cid, val)
    return text

def split_channel_and_detail(text):
    channels = ["EDC/K SHOP/MYQR", "โอนเข้า/หักบัญชีอัตโนมัติ", "K PLUS", "ตู้เติมเงิน / โมบาย แอปพลิ", 
                "Internet/Mobile KK", "K BIZ", "EDC", "ATM", "CDM", "BRANCH", "Internet/Mobile SCB", 
                "Internet/Mobile KTB", "Internet/Mobile BBL", "สาขาถนนศรีสุริยวงศ์", "สาขาเซ็นทรัล ขอนแก่น"]
    found_chan, detail = "-", text.strip()
    for c in channels:
        if c in text:
            found_chan = c
            detail = text.replace(c, "").strip().lstrip('/ ').strip()
            break
    return found_chan, detail

# ================= 2. ฟังก์ชันเฉพาะสำหรับ UOB (คงเดิม) =================
def clean_description(text):
    replacements = {"MISCCREDIT": "MISC CREDIT", "MISCDEBIT": "MISC DEBIT", "PAYMENTEO": "PAYMENT EO",
                    "INVOICENO": "INVOICE NO", "INTERESTCREDIT": "INTEREST CREDIT", "WITHHOLDINGTAXDR": "WITHHOLDING TAX DR"}
    for old, new in replacements.items(): text = text.replace(old, new)
    return re.sub(r'\s+', ' ', text).strip()

def is_garbage_line(line):
    garbage_keywords = ["Account Statement", "Movement Details - From:", "Statement", "Value Date", "Transaction", 
                        "Description", "Deposit", "Withdrawal", "Balance", "Date/Time", "Total in Account Currency", 
                        "Note:", "-Balances and details reflected are indicative", "TotalinAccountCurrency"]
    line_upper = line.upper()
    if any(kw.upper() in line_upper for kw in garbage_keywords): return True
    if re.match(r'^\d+\s?/\s?\d+$', line): return True
    if re.match(r'^\d{2}/\d{2}/\d{4}$', line): return True
    return False

def parse_uob_pdf(pdf_stream):
    all_rows = []
    current_row = None
    date_pattern = r'(\d{2}/\d{2}/\d{4})'
    row_start_pattern = fr'^({date_pattern})\s+({date_pattern})\s+({date_pattern})'
    time_pattern = r'(\d{2}:\d{2}:\d{2}\s?(?:AM|PM))'
    with pdfplumber.open(pdf_stream) as pdf_obj:
        for page in pdf_obj.pages:
            text = page.extract_text()
            if not text: continue
            for line in text.split('\n'):
                line = line.strip()
                if not line or is_garbage_line(line): continue
                match_dates = re.match(row_start_pattern, line)
                if match_dates:
                    if current_row: all_rows.append(current_row)
                    amounts = re.findall(r'[\d,]+\.\d{2}', line)
                    current_row = {"st_date": match_dates.group(1), "val_date": match_dates.group(2), "tx_date": match_dates.group(3),
                                   "tx_time": "", "desc": "", "deposit": 0.0, "withdrawal": 0.0, "balance": 0.0}
                    if len(amounts) >= 3:
                        current_row["deposit"] = str_to_float(amounts[-3])
                        current_row["withdrawal"] = str_to_float(amounts[-2])
                        current_row["balance"] = str_to_float(amounts[-1])
                        desc_part = line[33:].strip().split(amounts[-3])[0].strip()
                        current_row["desc"] = desc_part
                elif current_row and re.search(time_pattern, line):
                    t_match = re.search(time_pattern, line)
                    current_row["tx_time"] = t_match.group(1)
                    current_row["desc"] += " " + line.replace(t_match.group(1), "").strip()
                elif current_row: current_row["desc"] += " " + line
        if current_row: all_rows.append(current_row)
    return all_rows

# ================= 3. Parsers อื่นๆ (KBank, SCB, KTB, BBL) (คงเดิม) =================
# ===== 1.KBank =====
def parse_kbank_pdf(pdf_stream):
    all_parsed_rows = []
    bf_keywords = ["ยอดยกมา", "Balance Brought Forward", "Brought Forward"]
    table_headers = ["เวลา/", "วันที่มีผล", "ถอนเงิน / ฝากเงิน", "ยอดคงเหลือ", "ทำรายการ (บาท)"]
    with pdfplumber.open(pdf_stream) as pdf_obj:
        for page in pdf_obj.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split('\n')
            is_in_table = False 
            for line in lines:
                line = line.strip()
                if not line: continue
                date_match = re.match(r'^(\d{2}-\d{2}-\d{2})', line)
                if date_match:
                    is_in_table = True 
                    date = date_match.group(1)
                    time_match = re.search(r'(\d{2}:\d{2})', line)
                    time = time_match.group(1) if time_match else ""
                    amounts = re.findall(r'-?[\d,]+\.\d{2}', line)
                    temp_text = line.replace(date, "", 1).strip()
                    if time: temp_text = temp_text.replace(time, "", 1).strip()
                    desc = temp_text.split(amounts[0])[0].strip() if amounts else temp_text
                    amount_val, balance = None, None
                    if len(amounts) == 1:
                        balance = str_to_float(amounts[0])
                    elif len(amounts) >= 2:
                        is_deposit = any(kw in desc for kw in ["รับเงิน", "คืนเงิน", "ฝาก", "เงินคืน", "Thai QR", "รับโอนเงิน", "รับโอน", "รับเงินจาก"])
                        val = str_to_float(amounts[0])
                        amount_val = val if is_deposit else -val
                        balance = str_to_float(amounts[-1])
                    remaining = ""
                    if amounts:
                        parts = line.split(amounts[-1])
                        if len(parts) > 1: remaining = parts[-1].strip()
                    chan, det = split_channel_and_detail(remaining)
                    all_parsed_rows.append([date, time, desc, amount_val, balance, chan, det])
                    continue 
                if any(kw in line for kw in table_headers):
                    is_in_table = True
                    continue
                if any(kw in line for kw in ["Total", "รวมทั้งสิ้น", "จบรายการ"]):
                    is_in_table = False
                    continue
                if is_in_table:
                    if any(x in line for x in ["หน้า", "แผ่นที่", "ยอดคงเหลือ", "รวมถอนเงิน", "รวมฝากเงิน"]): 
                        continue
                    c_extra, d_extra = split_channel_and_detail(line)
                    all_parsed_rows.append(["", "", "", None, None, c_extra if c_extra != "-" else "", d_extra])
    rows_to_delete = set()
    n = len(all_parsed_rows)
    bf_indices = [idx for idx, row in enumerate(all_parsed_rows) if any(kw in str(row[2]) for kw in bf_keywords)]
    if bf_indices:
        keep_idx = None
        for idx in bf_indices:
            if all_parsed_rows[idx][0]: keep_idx = idx; break
        if keep_idx is None: keep_idx = bf_indices[0]
        for idx in bf_indices:
            if idx != keep_idx: rows_to_delete.add(idx)
    i = 0
    while i < n:
        if all_parsed_rows[i][0] == "" and all_parsed_rows[i][3] is None:
            start_block = i
            while i < n and all_parsed_rows[i][0] == "" and all_parsed_rows[i][3] is None: i += 1
            if (i - start_block) > 3:
                for k in range(start_block, i): rows_to_delete.add(k)
        else: i += 1
    return [row for idx, row in enumerate(all_parsed_rows) if idx not in rows_to_delete]

# ===== 2.SCB =====
def parse_scb_pdf(pdf_stream):
    all_parsed_rows = []
    header_found = False
    pending_desc = ""
    bf_keywords = ["ยอดยกมา", "BALANCE BROUGHT FORWARD", "ยอดเงินคงเหลือยกมา"]
    table_headers = ["Date", "Time", "Code", "Channel", "Cheque No.", "Withdrawal", "Deposit", "Description", "Balance/Baht", "วันที่", "เวลา", "รายการ"]
    ignore_keywords = table_headers + ["This document", "THE SIAM COMMERCIAL BANK", "Account No.", "Address", "TOTAL ITEMS"]
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split('\n')
            for line in lines:
                line_clean = line.strip()
                if not line_clean: continue
                if any(kw.upper() in line_clean.upper() for kw in bf_keywords):
                    amounts = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', line_clean)
                    if amounts: all_parsed_rows.append([None, None, "B/F", "-", 0.0, str_to_float(amounts[-1]), "ยอดยกมา"])
                    header_found = True; continue
                if ("Date" in line_clean and "Time" in line_clean) or ("วันที่" in line_clean and "เวลา" in line_clean):
                    header_found = True; continue 
                if not header_found or any(kw in line_clean for kw in ignore_keywords): continue
                transaction_match = re.match(r'^(\d{2}/\d{2}/\d{2,4})\s+(\d{2}:\d{2})', line_clean)
                if transaction_match:
                    date_str, time_str = transaction_match.groups()
                    amounts = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', line_clean)
                    parts = line_clean.replace(date_str, "").replace(time_str, "").strip().split()
                    code = parts[0] if parts else "-"
                    channel = parts[1] if len(parts) > 1 and not re.match(r'[\d,]+\.\d{2}', parts[1]) else "-"
                    amount_val, balance_val = 0.0, 0.0
                    if len(amounts) >= 2:
                        balance_val = str_to_float(amounts[-1])
                        raw_amount = str_to_float(amounts[-2])
                        amount_val = raw_amount if code.upper() in ['X1', 'IN', 'IT', 'BT', 'DP', 'CR', 'SD', 'C1', 'NR', 'TRN'] else -raw_amount
                    elif len(amounts) == 1: balance_val = str_to_float(amounts[0])
                    all_parsed_rows.append([date_str, time_str, code, channel, amount_val, balance_val, ""])
                elif all_parsed_rows:
                    all_parsed_rows[-1][6] = (all_parsed_rows[-1][6] + " " + line_clean).strip()
    return all_parsed_rows

# ===== 3.KTB (Digital/Rule-based) =====
def parse_ktb_pdf(pdf_stream):
    all_raw_rows = []
    deposit_codes = ['IORSDT', 'IIPS', 'DDSDT', 'CR', 'OTHDEP', 'PBSDT', 'NBSDT']
    bf_keywords = ["ยอดยกมา", "Balance Brought Forward"]
    ignore_keywords = ["ธนาคารกรุงไทย", "หน้า", "รายการเดินบัญชี", "บริษัท ธนาคารกรุงไทย"]
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = decode_cid(page.extract_text() or "")
            lines = text.split('\n')
            last_idx = -1
            for line in lines:
                line = line.strip()
                if not line or any(kw in line for kw in ignore_keywords) and not re.search(r'\d+\.\d{2}', line): continue
                if any(kw in line for kw in bf_keywords):
                    amts = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', line)
                    date_match = re.search(r'(\d{2}/\d{2}/\d{2,4})', line)
                    if amts:
                        all_raw_rows.append([date_match.group(1) if date_match else "", "", "B/F", "ยอดยกมา", 0.0, 0.0, str_to_float(amts[-1]), "-"])
                        last_idx = len(all_raw_rows) - 1; continue
                biz_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2})?\s*([A-Z0-9]+)\s+(.*)', line)
                if biz_match:
                    d, t, c, rem = biz_match.groups()
                    amts = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', rem)
                    if amts:
                        val = str_to_float(amts[0])
                        f_amt = val if any(dc in c for dc in deposit_codes) else -val
                        all_raw_rows.append([d, t or "", c, rem.split(amts[0])[0].strip(), f_amt, 0.0, str_to_float(amts[-1]), "KTB Digital"])
                        last_idx = len(all_raw_rows) - 1; continue
                pers_match = re.match(r'^(\d{2}/\d{2}/\d{2})\s*(.*?)\s*\(([A-Z]+)\)\s*(.*)', line)
                if pers_match:
                    d, name, c, rem = pers_match.groups()
                    amts = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', rem)
                    if amts:
                        w_amt, d_amt = str_to_float(amts[0]), str_to_float(amts[1]) if len(amts) > 2 else 0.0
                        f_amt = d_amt if d_amt > 0 else -w_amt
                        all_raw_rows.append([d, "", f"{name} ({c})", rem.split(amts[0])[0].strip(), f_amt, 0.0, str_to_float(amts[-1]), "KTB Pers"])
                        last_idx = len(all_raw_rows) - 1; continue
                if last_idx != -1 and not re.match(r'^\d{2}/\d{2}/', line):
                    all_raw_rows[last_idx][3] += " " + line
    return [r for r in all_raw_rows if r[4] != 0.0 or r[2] == "B/F"]

# ===== 4.BBL =====
def process_bbl_with_gemini(file_bytes, password):
    client = genai.Client(api_key=GEMINI_API_KEY_V1)
    unlocked_bytes = file_bytes
    try:
        with pikepdf.open(io.BytesIO(file_bytes), password=password) as pdf:
            out_pdf = io.BytesIO(); pdf.save(out_pdf); unlocked_bytes = out_pdf.getvalue()
    except: pass
    model_name = "gemini-2.5-flash" 
    prompt = """
    คุณคือ OCR ผู้เชี่ยวชาญด้านบัญชี โปรดอ่านสเตทเมนท์ธนาคารกรุงเทพ (BBL) นี้
    และคืนค่าเป็น JSON Array ของ Array เท่านั้น โดยมีลำดับคอลัมน์ดังนี้:
    [["วันที่ทำรายการ", "เวลา", "วันที่มีผล", "รายละเอียด", "เลขที่เช็ค", "จำนวนเงิน", "ยอดคงเหลือ", "ช่องทาง"]]
    กฎเหล็ก:
    1. วันที่: แปลง '26 มิ.ย. 2569' เป็น '26/06/2026'
    2. จำนวนเงิน: หักบัญชีติดลบ, เข้าบัญชีเป็นบวก
    3. คืนค่าเฉพาะ JSON
    """
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[types.Part.from_bytes(data=unlocked_bytes, mime_type="application/pdf"), prompt],
            config=types.GenerateContentConfig(response_mime_type='application/json'),
        )
        res_text = response.text.strip()
        if res_text.startswith("```"): res_text = res_text.replace("```json", "").replace("```", "").strip()
        return json.loads(res_text)
    except Exception as e:
        st.error(f"Gemini Error (BBL): {str(e)}"); return None

# ================= 4. Streamlit UI & Logic =================
st.title("📑 PDF Statement to Excel")

with st.sidebar:
    st.header("ตัวเลือก")
    bank_option = st.selectbox("เลือกธนาคาร", ["กสิกรไทย (KBank)", "ไทยพาณิชย์ (SCB)", "กรุงไทย (KTB)", "กรุงไทย (KTB Scan/Picture)", "กรุงศรี (BAY)", "กรุงเทพ (BBL)", "ยูโอบี (UOB)"])
    # แก้ไขให้รับไฟล์ภาพได้สำหรับ KTB Scan
    pdf_files = st.file_uploader("เลือกไฟล์", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
    password = st.text_input("รหัสผ่านไฟล์ (ถ้ามี)", type="password")
    convert_button = st.button("เริ่มการแปลงไฟล์", use_container_width=True)

if convert_button:
    if not pdf_files:
        st.error("⚠️ กรุณาเลือกไฟล์")
    else:
        all_dfs = []
        status_placeholder = st.empty()
        
        try:
            for i, uploaded_file in enumerate(pdf_files):
                status_placeholder.write(f"⏳ กำลังประมวลผล: {uploaded_file.name}...")
                file_bytes = uploaded_file.read()
                mime_type = uploaded_file.type
                df = None

                # --- 1. กลุ่มที่ใช้ AI ---
                if bank_option == "กรุงไทย (KTB Scan/Picture)":
                    data_rows = process_ktb_scan_with_gemini(file_bytes, mime_type)
                    if data_rows:
                        df = pd.DataFrame(data_rows, columns=["วันที่", "เวลา", "รายการ", "ถอนเงิน/ฝากเงิน", "ยอดคงเหลือ", "รายละเอียด"])
                        for col in ["ถอนเงิน/ฝากเงิน", "ยอดคงเหลือ"]:
                            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

                elif bank_option == "กรุงศรี (BAY)":
                    data_rows = process_bay_with_gemini(file_bytes, password)
                    if data_rows:
                        df = pd.DataFrame(data_rows, columns=["วันที่", "เวลา", "ถอนเงิน/ฝากเงิน", "ยอดคงเหลือ", "รหัส", "รายละเอียด", "ช่องทาง", "รหัสสาขา"])
                        df['วันที่'] = pd.to_datetime(df['วันที่'], dayfirst=True, errors='coerce')

                elif bank_option == "กรุงเทพ (BBL)":
                    data_rows = process_bbl_with_gemini(file_bytes, password)
                    if data_rows:
                        df = pd.DataFrame(data_rows, columns=["วันที่ทํารายการ", "เวลา", "วันที่มีผล", "รายละเอียด", "เลขที่เช็ค", "ถอนเงิน/ฝากเงิน", "ยอดคงเหลือ", "ช่องทาง"])
                        df['pdf_order'] = df.index 
                        df = df[df['เวลา'] != 'เวลา'] 
                        for col in ['ถอนเงิน/ฝากเงิน', 'ยอดคงเหลือ']:
                            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                        df['วันที่'] = df['วันที่ทํารายการ'].replace(r'^\s*$', pd.NA, regex=True).ffill()
                        df['datetime_sort'] = pd.to_datetime(df['วันที่'] + ' ' + df['เวลา'], dayfirst=True, errors='coerce')
                        df = df.sort_values(by=['datetime_sort', 'pdf_order'], ascending=[True, False]).reset_index(drop=True)
                        df = df.drop(columns=['pdf_order', 'datetime_sort'])

                # --- 2. กลุ่ม Rule-based (คงเดิม) ---
                else:
                    unlocked_io = io.BytesIO(file_bytes)
                    if mime_type == "application/pdf":
                        try:
                            with pikepdf.open(io.BytesIO(file_bytes), password=password) as pdf:
                                out_pdf = io.BytesIO(); pdf.save(out_pdf); out_pdf.seek(0); unlocked_io = out_pdf
                        except: pass
                    
                    if bank_option == "กสิกรไทย (KBank)":
                        rows = parse_kbank_pdf(unlocked_io)
                        df = pd.DataFrame(rows, columns=["วันที่", "เวลา", "รายการ", "ถอนเงิน/ฝากเงิน", "ยอดคงเหลือ", "ช่องทาง", "รายละเอียด"])
                    elif bank_option == "ไทยพาณิชย์ (SCB)":
                        rows = parse_scb_pdf(unlocked_io)
                        df = pd.DataFrame(rows, columns=["วันที่", "เวลา", "รายการ", "ช่องทาง", "ถอนเงิน/ฝากเงิน", "ยอดคงเหลือ", "รายละเอียด"])
                    elif bank_option == "กรุงไทย (KTB)":
                        rows = parse_ktb_pdf(unlocked_io)
                        df = pd.DataFrame(rows, columns=["วันที่", "เวลา", "รายการ", "รายละเอียด", "ถอนเงิน/ฝากเงิน", "ภาษี", "ยอดคงเหลือ", "สาขา"])
                    elif bank_option == "ยูโอบี (UOB)":
                        raw_uob = parse_uob_pdf(unlocked_io)
                        uob_data = [[r["st_date"], r["tx_date"], clean_description(r["desc"]), (r["deposit"] - r["withdrawal"]), r["balance"]] for r in raw_uob]
                        df = pd.DataFrame(uob_data, columns=["Statement Date", "Transaction Date", "Description", "ถอนเงิน/ฝากเงิน", "ยอดคงเหลือ"])

                if df is not None:
                    all_dfs.append(df)

            if all_dfs:
                final_df = pd.concat(all_dfs, ignore_index=True)
                st.dataframe(final_df, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    final_df.to_excel(writer, index=False, sheet_name='Statement')
                    workbook = writer.book
                    worksheet = writer.sheets['Statement']
                    
                    colors = {"กสิกรไทย (KBank)": '#00A950', "ไทยพาณิชย์ (SCB)": '#4E2E7F', "กรุงไทย (KTB)": '#00A1E0', "กรุงไทย (KTB Scan/Picture)": '#00A1E0', "กรุงศรี (BAY)": '#FFCC00', "กรุงเทพ (BBL)": '#0A22A8', "ยูโอบี (UOB)": '#003399'}
                    h_color = colors.get(bank_option, '#333333')
                    header_fmt = workbook.add_format({'bold': True, 'bg_color': h_color, 'font_color': 'white' if h_color != '#FFCC00' else 'black', 'align': 'center', 'border': 1})
                    num_fmt = workbook.add_format({'num_format': '#,##0.00', 'align': 'right'})
                    
                    for col_num, value in enumerate(final_df.columns.values):
                        worksheet.write(0, col_num, value, header_fmt)
                    worksheet.set_column('A:Z', 18)
                    for idx, col in enumerate(final_df.columns):
                        if any(kw in col for kw in ["ถอนเงิน", "ฝากเงิน", "ยอดคงเหลือ", "จำนวนเงิน", "ภาษี", "Balance"]):
                            worksheet.set_column(idx, idx, 15, num_fmt)

                output.seek(0)
                st.download_button(label="📥 ดาวน์โหลดไฟล์ Excel", data=output, file_name=f"Statement_{bank_option}_{datetime.now().strftime('%Y%m%d')}.xlsx")
                status_placeholder.success("✅ แปลงไฟล์สำเร็จ!")

        except PasswordError: st.error("❌ รหัสผ่านไม่ถูกต้อง")
        except Exception as e: st.error(f"❌ เกิดข้อผิดพลาด: {str(e)}")
