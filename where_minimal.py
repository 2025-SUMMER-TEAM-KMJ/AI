# where_minimal.py
import re, json
import google.generativeai as genai

# --- Gemini setup ---
genai.configure(api_key="AIzaSyCejgjuCnmrzsZfcSwPOcq02AOBxKM7bH0")
model = genai.GenerativeModel("models/gemini-2.5-flash")

BUCKET_SET = {
    "security","design","product","marketing","sales","cs",
    "data","ai_ml","frontend","backend","legal","logistics","hr",
    "manufacturing","strategy_exec","video_editing"
}

# ===== 200만원 단위 라벨 유틸 (LLM 폴백) =====
BIN = 2_000_000
_salary_re = re.compile(r"(\d{3,4})\s*만?\s*원?\s*(이상|이하|초과|미만)?")

def _to_man(x:int) -> int:
    return int(round(x / 10_000))

def _label_from_floor(floor:int) -> str:
    return f"{_to_man(floor):,}만~{_to_man(floor + BIN):,}만"

def _labels_from_range(min_krw: int | None, max_krw: int | None, cap:int=200_000_000) -> list[str]:
    """min~max를 200만원 단위 라벨 배열로. max가 None이면 cap까지."""
    if min_krw is None and max_krw is None:
        return []
    if min_krw is None:
        min_krw = 0
    floor = (min_krw // BIN) * BIN
    stop  = cap if max_krw is None else (max_krw // BIN) * BIN
    if stop < floor:
        floor, stop = stop, floor
    labels = []
    v = floor
    while v <= stop:
        labels.append(_label_from_floor(v))
        v += BIN
    return labels

def _labels_from_free_text(text: str) -> list[str]:
    """
    '3600만원 이상' 같은 문장에서 200만원 단위 라벨 배열 생성 (LLM이 못 뽑을 때 폴백)
    """
    m = _salary_re.search(text)
    if not m:
        return []
    amount_man = int(m.group(1))               # 3600
    cond = (m.group(2) or "").strip()
    base = amount_man * 10_000                 # KRW
    floor = (base // BIN) * BIN
    if cond in ("이상", "초과"):
        return _labels_from_range(floor, None)
    elif cond in ("이하", "미만"):
        return _labels_from_range(None, floor)
    else:
        return [_label_from_floor(floor)]

# ===== 프롬프트 =====
# JSON 예시 등 리터럴 중괄호는 모두 {{ }} 로 이스케이프
PROMPT = """너는 채용 추천용 필터 추출기야.
사용자 문장에서 존재하는 항목만 추출해 **JSON만** 출력해. 모르면 그 키는 생략.

허용 키:
- bucket: 아래 목록 중 하나(단일값)
- buckets: 아래 목록 중 2개 이상(복수값이 더 자연스러울 때 사용)
  [security, design, product, marketing, sales, cs,
   data, ai_ml, frontend, backend, legal, logistics, hr, manufacturing, strategy_exec, video_editing]
- location: 시/도 명칭 (예: "서울", "경기", "부산", "인천" 등)
- district: 시/군/구 명칭을 그대로 (예: "강남구", "성남시", "분당구", "도봉구" 등)
- 성동구나 강남구 일대, 강남/성동, 강남구 또는 성동구 처럼 **복수 구/시**가 언급되면 district 대신 **districts**로 여러 개 제시
- salary_bucket_2m_label: 문자열 배열. 200만원 단위 구간 문자열만 담는다 (예: ["5,400만~5,600만"])

규칙:
- 존재하는 키만 포함(없으면 아예 생략)
- 애매하면 bucket 대신 **buckets**로 여러 개 제시, 하지만 자바스크립트처럼 확실히 프론트인건 bucket
- 성동구나 강남구 일대 이런 식으로 애매하게 제시하면 district 대신 **districts**로 여러개 제시
- 연봉 조건이 나오면 salary_bucket_2m_label 키를 사용
  • salary_bucket_2m_label의 각 원소는 "2,000만~2,200만"처럼 200만원 단위 구간 문자열
  • "5600만원 이상" → 해당 구간 이상부터 2억까지 모두 배열로 출력
  • "4000만원 이하" → 해당 구간 이하부터 3개 구간까지 배열로 출력
  • "5200만원" 또는 "5400만~5600만" → 해당 구간 이상 부터 3개 배열로 출력
- 애매하면 bucket 대신 buckets를 사용
- JSON 객체 **한 줄만** 출력하고 다른 텍스트 금지

예시 출력:
{{"buckets":["ai_ml","backend"],"location":"서울","district":"강남구","salary_bucket_2m_label":["5,600만~5,800만","5,800만~6,000만", "6,000만~6,200만"]}}
{{"districts":["강남구","성동구"]}}

사용자 문장: {query}
"""

# ===== JSON 추출 =====
def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text.strip(), flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}

# ===== 빌더 =====
def build_where_from_llm(query: str) -> dict:
    # 1) LLM 호출
    resp = model.generate_content(PROMPT.format(query=query))
    txt = (getattr(resp, "text", "") or "").strip()
    obj = _extract_json(txt)

    # 2) 있는 키만 where로 조립
    conds = []

    # 단일 bucket
    b = obj.get("bucket")
    if isinstance(b, str) and b in BUCKET_SET:
        conds.append({"bucket": b})

    # 복수 buckets -> $in
    bs = obj.get("buckets")
    if isinstance(bs, list):
        valid = [x for x in bs if isinstance(x, str) and x in BUCKET_SET]
        valid = list(dict.fromkeys(valid))
        if len(valid) == 1:
            conds.append({"bucket": valid[0]})
        elif len(valid) > 1:
            conds.append({"bucket": {"$in": valid}})

    # 지역
    loc = obj.get("location")
    if isinstance(loc, str) and loc.strip():
        conds.append({"location": loc.strip()})
        
    # ---- district / districts (여기가 핵심) ----
    # 단일 district
    dist = obj.get("district")
    if isinstance(dist, str) and dist.strip():
        conds.append({"district": dist.strip()})

    # 복수 districts -> $in
    dists = obj.get("districts")
    if isinstance(dists, list):
        vals = [d for d in dists if isinstance(d, str) and d.strip()]
        vals = list(dict.fromkeys(vals))
        if len(vals) == 1:
            conds.append({"district": vals[0]})
        elif len(vals) > 1:
            conds.append({"district": {"$in": vals}})

    # 연봉(버킷 라벨): LLM 결과 우선
    labels = []
    sal = obj.get("salary_bucket_2m_label")
    if isinstance(sal, list):
        labels = [s for s in sal if isinstance(s, str) and s.strip()]
    elif isinstance(sal, str) and sal.strip():
        labels = [sal.strip()]

    # 폴백: LLM이 못 뽑으면 free-text에서 직접 생성
    if not labels:
        labels = _labels_from_free_text(query)

    if labels:
        if len(labels) == 1:
            conds.append({"salary_bucket_2m_label": labels[0]})
        else:
            conds.append({"salary_bucket_2m_label": {"$in": labels}})

    if not conds:
        return {}
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}

# ===== quick test =====
if __name__ == "__main__":
    samples = [
        "강남구 프론트엔드 공고 추천해줘",
        "성남시 백엔드 포지션 있어?",
        "부산 마케팅 채용 알려줘",
        "강남구나 성동구에서 일할 만한 데이터 엔지니어",
        "공항대로 근처 알고리즘/제어 쪽 포지션",
        "추천·랭킹 시스템이나 제어 알고리즘 포지션",
        "3600만원 이상 버는 백엔드",
        "서울 5200만원 프론트",
        "4000만원 이하 CS"
    ]
    for s in samples:
        print(s, "=>", build_where_from_llm(s))
