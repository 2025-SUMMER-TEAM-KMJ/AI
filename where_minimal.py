# where_minimal.py
import os, re, json
import google.generativeai as genai

genai.configure(api_key="AIzaSyCejgjuCnmrzsZfcSwPOcq02AOBxKM7bH0")
model = genai.GenerativeModel("models/gemini-2.5-flash")

BUCKET_SET = {
    "security","design","product","marketing","sales","cs",
    "data_engineering","ai_ml","frontend","backend","legal","logistics","hr"
}

PROMPT = """너는 채용 추천용 필터 추출기야.
사용자 문장에서 존재하는 항목만 추출해 **JSON만** 출력해. 모르면 그 키는 생략.

허용 키:
- bucket: 아래 목록 중 하나만 사용
  [security, design, product, marketing, sales, cs,
   data_engineering, ai_ml, frontend, backend, legal, logistics, hr]
- location: 시/도 명칭 (예: "서울", "경기", "부산", "인천" 등)
- district: 시/군/구 명칭을 그대로 (예: "강남구", "성남시", "분당구", "도봉구" 등)

규칙:
- 존재하는 키만 포함(없으면 아예 생략)
- 값은 문자열
- JSON 객체 한 줄만 출력하고 다른 텍스트 금지

예시 출력:
{{"bucket":"frontend","location":"서울","district":"강남구"}}

사용자 문장: {query}
"""

def _extract_json(text: str) -> dict:
    """혹시 모델이 앞뒤에 뭔가 붙여도 중괄호 블록만 파싱."""
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

    # 2) 있는 키만 where로
    conds = []
    b = obj.get("bucket")
    if isinstance(b, str) and b in BUCKET_SET:
        conds.append({"bucket": b})
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

# --- quick test ---
if __name__ == "__main__":
    samples = [
        "강남구 프론트엔드 공고 추천해줘",
        "성남시 백엔드 포지션 있어?",
        "부산 마케팅 채용 알려줘",
        "도봉구에서 일할 만한 데이터 엔지니어"
    ]
    for s in samples:
        print(s, "=>", build_where_from_llm(s))
