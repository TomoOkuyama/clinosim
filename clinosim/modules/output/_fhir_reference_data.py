"""Pure FHIR reference-data dictionaries (code/SNOMED/region lookup tables).

FA-1 Phase 2: module-level data literals extracted verbatim from
fhir_r4_adapter.py. These are pure data (no functions, no dependencies on
other adapter symbols) and are re-exported by fhir_r4_adapter as a facade.
"""

from __future__ import annotations

_ALLERGEN_RXNORM: dict[str, str] = {
    # RxNorm ingredient codes for common drug allergens
    "Penicillin": "7980",
    "Sulfonamide": "10180",
    "NSAIDs": "5640",  # ibuprofen as representative
    "Cephalosporin": "2173",
    "Aspirin": "1191",
}


_CONDITION_SHORT_NAME: dict[str, dict[str, str]] = {
    # Respiratory
    "J44": {"en": "COPD", "ja": "COPD（慢性閉塞性肺疾患）"},
    "J45": {"en": "Asthma", "ja": "喘息"},
    "J15": {"en": "Bacterial pneumonia", "ja": "細菌性肺炎"},
    "J12": {"en": "Viral pneumonia", "ja": "ウイルス性肺炎"},
    "J18": {"en": "Pneumonia", "ja": "肺炎"},
    "J69": {"en": "Aspiration pneumonia", "ja": "誤嚥性肺炎"},
    "J10": {"en": "Influenza", "ja": "インフルエンザ"},
    # Cardiovascular
    "I50": {"en": "Heart failure (CHF)", "ja": "心不全"},
    "I21": {"en": "Acute MI", "ja": "急性心筋梗塞"},
    "I25": {"en": "Chronic ischemic heart disease (IHD)", "ja": "慢性虚血性心疾患"},
    "I48": {"en": "Atrial fibrillation (AF)", "ja": "心房細動"},
    "I10": {"en": "Hypertension (HTN)", "ja": "高血圧"},
    "I63": {"en": "Cerebral infarction (stroke)", "ja": "脳梗塞"},
    "I61": {"en": "Hemorrhagic stroke (ICH)", "ja": "脳出血"},
    "I26": {"en": "Pulmonary embolism (PE)", "ja": "肺塞栓"},
    "I80": {"en": "DVT", "ja": "深部静脈血栓症"},
    "I82": {"en": "DVT", "ja": "深部静脈血栓症"},
    # Endocrine
    "E11": {"en": "Type 2 diabetes (DM)", "ja": "2型糖尿病"},
    "E10": {"en": "Type 1 diabetes (DM)", "ja": "1型糖尿病"},
    "E78": {"en": "Dyslipidemia", "ja": "脂質異常症"},
    "E03": {"en": "Hypothyroidism", "ja": "甲状腺機能低下症"},
    # Renal
    "N18": {"en": "CKD", "ja": "慢性腎臓病"},
    "N17": {"en": "AKI", "ja": "急性腎障害"},
    "N10": {"en": "Acute pyelonephritis (UTI)", "ja": "急性腎盂腎炎"},
    "N39": {"en": "UTI", "ja": "尿路感染症"},
    # GI
    "K21": {"en": "GERD", "ja": "逆流性食道炎"},
    "K85": {"en": "Acute pancreatitis", "ja": "急性膵炎"},
    "K80": {"en": "Cholelithiasis", "ja": "胆石症"},
    "K81": {"en": "Cholecystitis", "ja": "胆嚢炎"},
    "K92": {"en": "GI bleeding", "ja": "消化管出血"},
    "K56": {"en": "Ileus", "ja": "イレウス"},
    "K74": {"en": "Liver cirrhosis", "ja": "肝硬変"},
    # Musculoskeletal
    "M17": {"en": "Knee OA", "ja": "変形性膝関節症"},
    "M81": {"en": "Osteoporosis", "ja": "骨粗鬆症"},
    "S72": {"en": "Hip fracture", "ja": "大腿骨骨折"},
    # Neurological
    "F00": {"en": "Alzheimer's dementia", "ja": "アルツハイマー型認知症"},
    "G20": {"en": "Parkinson's disease (PD)", "ja": "パーキンソン病"},
    # Infectious
    "A41": {"en": "Sepsis", "ja": "敗血症"},
    "R65": {"en": "Severe sepsis / septic shock", "ja": "重症敗血症"},
    "L03": {"en": "Cellulitis", "ja": "蜂窩織炎"},
    # Prostate
    "N40": {"en": "BPH", "ja": "前立腺肥大症"},
    # DKA
    "E13": {"en": "DKA", "ja": "糖尿病性ケトアシドーシス"},
}


_SEVERITY_SNOMED: dict[str, dict[str, str]] = {
    "mild": {"code": "255604002", "display": "Mild"},
    "moderate": {"code": "6736007", "display": "Moderate"},
    "severe": {"code": "24484000", "display": "Severe"},
}


_PREFECTURE_CODE: dict[str, str] = {
    "北海道": "01", "青森県": "02", "岩手県": "03", "宮城県": "04", "秋田県": "05",
    "山形県": "06", "福島県": "07", "茨城県": "08", "栃木県": "09", "群馬県": "10",
    "埼玉県": "11", "千葉県": "12", "東京都": "13", "神奈川県": "14", "新潟県": "15",
    "富山県": "16", "石川県": "17", "福井県": "18", "山梨県": "19", "長野県": "20",
    "岐阜県": "21", "静岡県": "22", "愛知県": "23", "三重県": "24", "滋賀県": "25",
    "京都府": "26", "大阪府": "27", "兵庫県": "28", "奈良県": "29", "和歌山県": "30",
    "鳥取県": "31", "島根県": "32", "岡山県": "33", "広島県": "34", "山口県": "35",
    "徳島県": "36", "香川県": "37", "愛媛県": "38", "高知県": "39", "福岡県": "40",
    "佐賀県": "41", "長崎県": "42", "熊本県": "43", "大分県": "44", "宮崎県": "45",
    "鹿児島県": "46", "沖縄県": "47",
}


_ENCOUNTER_TYPE_SNOMED: dict[str, dict[str, str]] = {
    "inpatient": {"code": "32485007", "display": "Hospital admission"},
    "emergency": {"code": "50849002", "display": "Emergency hospital admission"},
    "outpatient": {"code": "270427003", "display": "Patient-initiated encounter"},
    "icu": {"code": "183452005", "display": "Emergency hospital admission"},
}


_ENCOUNTER_TYPE_SNOMED_JA: dict[str, str] = {
    "inpatient": "入院",
    "emergency": "救急入院",
    "outpatient": "外来受診",
    "icu": "救急入院",
}


_ROUTE_SNOMED: dict[str, dict[str, str]] = {
    "PO": {"code": "26643006", "display": "Oral"},
    "IV": {"code": "47625008", "display": "Intravenous"},
    "SC": {"code": "34206005", "display": "Subcutaneous"},
    "IM": {"code": "78421000", "display": "Intramuscular"},
    "SL": {"code": "37161004", "display": "Sublingual"},
    "PR": {"code": "37161004", "display": "Per rectum"},
    "INHALED": {"code": "447694001", "display": "Inhalation"},
    "TOPICAL": {"code": "6064005", "display": "Topical"},
    "NEBULIZED": {"code": "447694001", "display": "Inhalation"},
}


_ROLE_PREFIX_MAP: dict[str, dict[str, str]] = {
    "physician": {"qual_code": "MD", "qual_display": "Doctor of Medicine"},
    "nurse": {"qual_code": "RN", "qual_display": "Registered Nurse"},
    "lab_technician": {"qual_code": "MT", "qual_display": "Medical Technologist"},
    "radiologist": {"qual_code": "MD", "qual_display": "Doctor of Medicine"},
    "pharmacist": {"qual_code": "PharmD", "qual_display": "Doctor of Pharmacy"},
}


_SPECIALTY_SNOMED: dict[str, dict[str, str]] = {
    "general": {"code": "419192003", "display": "Internal Medicine"},
    "cardiology": {"code": "394579002", "display": "Cardiology"},
    "pulmonology": {"code": "418112009", "display": "Pulmonary medicine"},
    "gastro": {"code": "394584008", "display": "Gastroenterology"},
    "nephro": {"code": "394589003", "display": "Nephrology"},
    "endo": {"code": "394583003", "display": "Endocrinology"},
    "internal_medicine": {"code": "419192003", "display": "Internal Medicine"},
    "radiology": {"code": "394914008", "display": "Radiology"},
    "laboratory": {"code": "722414000", "display": "Laboratory medicine"},
    "pharmacy": {"code": "405623001", "display": "Pharmacy"},
}
