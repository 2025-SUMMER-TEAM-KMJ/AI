# where_minimal.py
import re, json
import google.generativeai as genai

genai.configure(api_key="AIzaSyCejgjuCnmrzsZfcSwPOcq02AOBxKM7bH0")
model = genai.GenerativeModel("models/gemini-2.5-flash")

BUCKET_SET = {
    "security","design","product","marketing","sales","cs",
    "data_engineering","ai_ml","frontend","backend","legal","logistics","hr",
    "manufacturing"
}

# JSON 예시 등 리터럴 중괄호는 모두 {{ }} 로 이스케이프
PROMPT = """너는 채용 추천용 필터 추출기야.
사용자 문장에서 존재하는 항목만 추출해 **JSON만** 출력해. 모르면 그 키는 생략.

허용 키:
- bucket: 아래 목록 중 하나(단일값)
- buckets: 아래 목록 중 2개 이상(복수값이 더 자연스러울 때 사용)
  [security, design, product, marketing, sales, cs,
   data_engineering, ai_ml, frontend, backend, legal, logistics, hr, manufacturing]
- location: 시/도 명칭 (예: "서울", "경기", "부산", "인천" 등)
- district: 시/군/구 명칭을 그대로 (예: "강남구", "성남시", "분당구", "도봉구" 등)

규칙:
- 존재하는 키만 포함(없으면 아예 생략)
- 값은 문자열(bucket) 또는 문자열 배열(buckets)
- 애매하면 bucket 대신 **buckets**로 여러 개 제시
- JSON 객체 한 줄만 출력하고 다른 텍스트 금지

참고 지명 유추 예시:
- "공항대로" ⇒ district="강서구", location="서울"
- "테헤란로" ⇒ district="강남구", location="서울"
- "가산디지털단지" ⇒ district="금천구", location="서울"
- "정자역" ⇒ district="분당구", location="경기"   # 성남시 분당구

예시 출력:
{{"buckets":["ai_ml","backend","manufacturing"],"location":"서울","district":"강남구"}}

사용자 문장: {query}
"""

def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text.strip(), flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}

def build_where_from_llm(query: str) -> dict:
    # 1) LLM 호출
    resp = model.generate_content(PROMPT.format(query=query))
    txt = (resp.text or "").strip()
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

    loc = obj.get("location")
    if isinstance(loc, str) and loc.strip():
        conds.append({"location": loc.strip()})

    dist = obj.get("district")
    if isinstance(dist, str) and dist.strip():
        conds.append({"district": dist.strip()})

    if not conds:
        return {}
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}

# quick test
if __name__ == "__main__":
    samples = [
        "강남구 프론트엔드 공고 추천해줘",
        "성남시 백엔드 포지션 있어?",
        "부산 마케팅 채용 알려줘",
        "도봉구에서 일할 만한 데이터 엔지니어",
        "공항대로 근처 알고리즘/제어 쪽 포지션",
        "추천·랭킹 시스템이나 제어 알고리즘 포지션"
    ]
    for s in samples:
        print(s, "=>", build_where_from_llm(s))
