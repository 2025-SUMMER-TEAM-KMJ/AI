# bucket_classify_preview.py
# 목적: 필터링
# 단계:
#   1) 직무명(title) 우선 룰 매칭
#   2) 본문 보조 룰(우선순위 기반)
#   3) 둘 다 실패하면 'etc'

# security, design, product, marketing, sales, cs, manufacturing, data, ai_ml, frontend, backend, legal, logistics, hr, strategy_exec, video_editing

# 설명:
# - Mongo에서 채용 공고를 읽어 룰 기반으로 bucket 분류
# - address.location / address.district 를 최상위 location / district 로 "확실히" 백필(루프 방식)
# - bucket/위치 필드를 Mongo에 저장

import re
from collections import Counter
from typing import Any, Dict, List, Optional
from pymongo import MongoClient

# ====== Mongo 설정 ======
MONGO_URI = "mongodb://root:root@35.192.157.46:27017/?authSource=admin"
DB_NAME = "db"
COLL_NAME = "master_job_postings"

# ===== 금칙어 =====
# (선택) 플래그 공통화
FLAGS = re.IGNORECASE

# 버킷별 금지(역필터): 본문에 나오면 해당 버킷을 제외
BODY_DENY = {
    "marketing": [r"개발자|엔지니어|프로그래머|api|배포|db|알고리즘|공정|품질|라인|설비"],
    "backend":   [r"마케터|마케팅|영업|세일즈|디자이너|브랜딩|총무|인사|회계|법무|물류"],
    "frontend":  [r"마케터|마케팅|영업|세일즈|회계|법무|물류|공정|품질|라인|설비"],
    "data":      [r"영업(?!\s*데이터)|세일즈(?!\s*데이터)|브랜딩|법무|공정|라인"],
    "ai_ml":     [r"영업|세일즈|브랜딩|법무|공정|라인"],
    "design":    [r"서버|백엔드|프로그래밍|공정|라인|설비|법무|회계"],
    "sales":     [r"개발자|엔지니어|프로그래머|공정|라인|설비|법무|회계"],
    "cs":        [r"개발자|엔지니어|프로그래머|마케터|브랜딩|법무|공정|라인|설비"],
    "hr":        [r"개발자|엔지니어|프로그래머|마케터|브랜딩|공정|라인|설비"],
    "legal":     [r"개발자|엔지니어|프로그래머|마케터|브랜딩|공정|라인|설비"],
    "logistics": [r"개발자|엔지니어(?!\s*설비)|프로그래머|브랜딩|법무|회계|디자인"],
    "manufacturing": [r"마케터|브랜딩|영업|세일즈|법무|회계|디자인|광고"],
    "strategy_exec": [r"영상\s*편집|유튜브|퍼포먼스\s*마케터"],
    "video_editing": [r"개발자|엔지니어|서버|공정|라인|설비|법무|회계"]
}

# (선택) 충돌 시 우선순위 — 없으면 아래 match_by_rules의 PRIORITY 루프를 지워도 OK
PRIORITY = [
    "security", "backend", "frontend", "data", "ai_ml",
    "manufacturing", "logistics",
    "design", "marketing", "sales", "cs", "hr", "legal",
    "video_editing", "product", "strategy_exec"
]

# ====== 1) 직무명(title) 우선 룰 ======
TITLE_RULES = [
    ("design", [
        r"디자이너",
        r"designer",
        r"\b2d\b|2d\s*디자이너",
        r"ui[,/\s]*gui\s*디자이너|ui\s*디자이너",
        r"ux\s*디자이너|\bux\b\s*디자이너",
        r"웹\s*디자이너|그래픽\s*디자이너|bi/bx\s*디자이너|브랜드\s*디자이너",
        r"제품\s*디자이너|산업\s*디자이너",
        r"공간\s*디자이너|인테리어\s*디자이너|출판[,\s]*편집\s*디자이너"
    ]),
    ("security", [
        r"보안\s*엔지니어|정보보호|security",
        r"시스템.*관리자|네트워크\s*관리자|\bsre\b|\bsoc\b|\bsiem\b|시스템.*관리자|네트워크\s*관리자"
    ]),
    ("product", [
        r"pm·?po|\bpo\b|product\s*(manager|owner)|프로덕트\s*매니저|서비스\s*기획",
        r"전략\s*기획자?|사업개발|biz\s*dev|\bbd\b",
        r"서비스\s*운영\s*매니저|프로덕트\s*운영\s*매니저",
        r"교육\s*기획|교재"
    ]),
    ("marketing", [
        r"\b마케터\b|마케팅|브랜드|콘텐츠\s*마케터|퍼포먼스\s*마케터|\bbtl\b|\bpr\b|홍보",
        r"글로벌\s*마케팅|소셜\s*마케터|키워드\s*광고",
        r"통[·\s]*번역|locali[sz]ation|로컬라이제이션"
    ]),
    ("sales", [
        r"영업|세일즈|account\s*executive|대면\s*영업",
        r"key\s*account|주요고객사\s*담당자|\bkam\b|유통\s*관리자|리테일\s*md|매장\s*(관리자|점원)|기술영업|해외영업"
    ]),
    ("cs", [
        r"\bcs\b|고객성공|customer\s*success|고객\s*응대|voc|콜\s*센터|서비스\s*운영|운영\s*매니저|오피스\s*관리|총무|유지보수\s*관리자",
        r"cs\s*운영\s*매니저|고객\s*운영\s*매니저"
    ]),
    ("manufacturing", [
        r"품질\s*관리자|qa|qc|검사|inspec|quality",
        r"생산|제조|공정|라인|설비\s*엔지니어|장비\s*엔지니어|시운전\s*엔지니어|현장\s*소장"
    ]),
    ("legal", [r"법무|특허|compliance|준법|계약|라이(?:센|선)스\s*관리자|\blicense\b"]),
    ("logistics", [r"물류|입·출고|배송|무역\s*사무|수출입|현장\s*소장|구매\s*담당|생산\s*관리자|자재관리"]),
    ("hr", [r"인사|리크루터|헤드헌터|\bhrbp\b|\bhrd\b|평가·보상|회계|경리|재무|자금"]),
    ("strategy_exec", [
    r"\bcio\b|chief\s*information\s*officer",
    r"\bceo\b|chief\s*executive\s*officer",
    r"\bcto\b|chief\s*technology\s*officer",
    r"컨설턴트"
    ]),
    ("video_editing", [
    r"영상\s*편집|video\s*editing|video\s*editor|동영상\s*편집",
    r"영상\s*제작|video\s*production|촬영\s*및\s*편집",
    r"모션\s*그래픽|motion\s*graphics?|영상\s*그래픽",
    r"프리미어\s*프로|after\s*effects?|프리미어\s*에프터이펙트",
    r"유튜브\s*영상|youtube\s*video"
    ]),
    ("data", [
        r"데이터\s*엔지니어|data\s*engineer|빅데이터\s*엔지니어|\bdba\b|etl|spark|hadoop|airflow|kafka",
        r"데이터\s*분석가|data\s*analyst",
        r"데이터\s*사이언티스트|data\s*scientist"
    ]),
    ("ai_ml", [
        r"머신러닝|machine\s*learning|\bml\b|딥러닝|deep\s*learning",
        r"\bnlp\b|computer\s*vision|recommendation|mle"
    ]),
    ("frontend", [
    r"프론트\s*(엔드)?|\bfrontend\b",
    r"웹\s*퍼블리셔|웹\s*퍼블리싱",                 # 'publisher' 단독 제거
    r"(react|vue|svelte)(?!\s*native)",            # RN 제외
    r"next\.js\b|nuxt\.js\b",
    r"(typescript|ts)\b(?=.*\b(react|vue|next|spa|dom|브라우저)\b)",  # 동시조건
    r"ui\s*개발자(?=.*\b(react|vue|spa|dom|프론트)\b)"               # 보조조건
    ]),

    ("backend", [
        r"백엔드|\bbackend\b|서버\s*개발자|\bjava\b|\bspring\b|node\.js|\bnode\b|php|\.net|\bgolang\b|\bgo\b|django|fastapi|nestjs|msa|microservices|자바",
        r"c\+\+|c/c\+\+|임베디드|embedded|erp|sap|oracle"
    ])


]

# ====== 2) 본문 보조 룰 ======
BODY_RULES = [
    ("security", [r"보안\s*엔지니어|정보보호|security|\bsre\b|\bsoc\b|\bsiem\b"]),
    ("design", [r"\bux\b|ux\s*디자이너|ui[,/\s]*gui\s*디자이너|ui\s*디자이너|그래픽\s*디자이너|\b(bi|bx)\b\s*디자이너|브랜딩|웹\s*디자이너|제품\s*디자이너|산업\s*디자이너"]),
    ("product", [r"\bpm\b|product\s*(manager|owner)|프로덕트\s*매니저|서비스\s*기획|전략\s*기획|사업개발|교육\s*기획|교재|운영\s*매니저"]),
    ("marketing", [r"마케터|마케팅|브랜드|콘텐츠\s*마케터|퍼포먼스\s*마케터|리테일\s*md|\bpr\b|홍보|로컬라이제이션|키워드\s*광고|\bbtl\b"]),
    ("sales", [r"영업|세일즈|account\s*executive|key\s*account|\bkam\b|유통\s*관리자|매장\s*(관리자|점원)|기술영업|해외영업"]),
    ("cs", [r"\bcs\b|customer\s*success|고객\s*응대|voc|콜\s*센터|서비스\s*운영|(cs|고객)\s*운영\s*매니저|오피스\s*관리|총무|유지보수\s*관리자"]),
    ("legal", [r"법무|특허|compliance|준법|계약|라이(?:센|선)스"]),
    ("logistics", [r"물류|입·출고|배송|무역\s*사무|수출입|현장\s*소장|구매\s*담당|생산\s*관리자|자재관리"]),
    ("hr", [r"인사|리크루터|헤드헌터|\bhrbp\b|\bhrd\b|평가·보상|회계|경리|재무|자금"]),
    ("manufacturing", [r"테스트\s*엔지니어|품질\s*관리자|qa|qc|검사|inspec|quality|생산|제조|공정|라인|설비\s*엔지니어|장비\s*엔지니어|시운전\s*엔지니어|현장\s*소장"]),
    ("strategy_exec", [ r"\b(cio|ceo|cto)\b|chief\s*(information|executive|technology)\s*officer|컨설턴트"]),
    ("video_editing", [r"영상\s*편집|video\s*editing|video\s*editor|동영상\s*편집|영상\s*제작|video\s*production|촬영\s*및\s*편집|모션\s*그래픽|motion\s*graphics?|영상\s*그래픽|프리미어\s*프로|after\s*effects?|프리미어\s*에프터이펙트|유튜브\s*영상|youtube\s*video"]),
    ("data", [r"데이터\s*엔지니어|data\s*engineer|빅데이터|\bdba\b|etl|spark|hadoop|airflow|kafka|데이터\s*분석가|data\s*analyst|데이터\s*사이언티스트|data\s*scientist"]),
    ("ai_ml", [r"머신러닝|machine\s*learning|\bml\b|딥러닝|deep\s*learning|\bnlp\b|computer\s*vision|recommendation|mle"]),
    ("frontend", [r"프론트엔드|\bfrontend\b|웹\s*퍼블리셔|\bpublisher\b|ui\s*개발자|react|vue|typescript|next\.js|svelte|모바일|ios|android|react\s*native|flutter|unity|unreal|게임\s*클라이언트"]),
    ("backend", [r"백엔드|backend|서버\s*개발자|java|spring|node\.js|php|\.net|golang|\bgo\b|django|fastapi|nestjs|msa|microservices|c\+\+|임베디드|embedded|erp|sap|oracle"]),

]

# ====== 유틸 ======
def _get(doc: Dict[str, Any], path: List[str]) -> Any:
    x = doc
    for k in path:
        if not isinstance(x, dict):
            return None
        x = x.get(k)
    return x

def extract_title(doc: Dict[str, Any]) -> str:
    for path in (["job"], ["position","job"], ["detail","position","job"]):
        v = _get(doc, path)
        if isinstance(v, list) and v:
            return str(v[0])
        if isinstance(v, str) and v.strip():
            return v
    intro = _get(doc, ["detail","intro"])
    if isinstance(intro, str) and intro.strip():
        return intro.strip().splitlines()[0][:80]
    return ""

def gather_body(doc: Dict[str, Any]) -> str:
    buf = []
    for path in (["detail","intro"], ["detail","main_tasks"], ["detail","requirements"]):
        v = _get(doc, path)
        if isinstance(v, str) and v.strip():
            buf.append(v)
    body = "\n".join(buf).lower()
    return body[:10000]

def match_by_rules(title: str, body: str) -> Optional[str]:
    t = (title or "").lower()
    b = (body  or "").lower()

    # 1) 제목 우선(기존과 동일)
    for bucket, patterns in TITLE_RULES:
        for p in patterns:
            if re.search(p, t, flags=FLAGS):
                return bucket

    # 2) 본문 매칭 → 후보 수집
    candidates = []
    for bucket, patterns in BODY_RULES:
        if any(re.search(p, b, flags=FLAGS) for p in patterns):
            candidates.append(bucket)

    if not candidates:
        return None

    # deny 트리거 있으면 후보 제외
    filtered = []
    for bkt in candidates:
        if any(re.search(p, b, FLAGS) for p in BODY_DENY.get(bkt, [])):
            continue
        filtered.append(bkt)

    if not filtered:
        filtered = candidates  # 모두 걸러지면 원후보 사용(너무 공격적 컷 방지)

    # (선택) 우선순위 기반 최종 선택
    if 'PRIORITY' in globals():
        for p in PRIORITY:
            if p in filtered:
                return p

    return filtered[0]

def classify_doc(doc: Dict[str, Any]) -> (str, str, str):
    rid = str(doc.get("_id"))
    title = extract_title(doc)
    body = gather_body(doc)
    bucket = match_by_rules(title, body) or "etc"
    return rid, title or "(no-title)", bucket


def main(limit: Optional[int] = None, save: bool = False):
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    col = client[DB_NAME][COLL_NAME]

    # ===== (1) address 하위 → 최상위로 "확실히" 복사 (루프 방식) =====
    cnt_loc = cnt_dist = 0
    for d in col.find({"address.location": {"$type":"string"}}, {"address.location":1}):
        val = (d["address"]["location"] or "").strip()
        if val:
            res = col.update_one({"_id": d["_id"]}, {"$set": {"location": val}})
            cnt_loc += res.modified_count
    for d in col.find({"address.district": {"$type":"string"}}, {"address.district":1}):
        val = (d["address"]["district"] or "").strip()
        if val:
            res = col.update_one({"_id": d["_id"]}, {"$set": {"district": val}})
            cnt_dist += res.modified_count
    print(f"[BACKFILL] location set: {cnt_loc}, district set: {cnt_dist}")

    # ===== (2) 분류 수행 + bucket/위치 저장 =====
    cursor = col.find({}, {"_id":1, "job":1, "position":1, "detail":1, "address":1, "location":1, "district":1}).limit(limit or 0)

    results = []
    for doc in cursor:
        rid, title, bucket = classify_doc(doc)
        results.append((rid, title, bucket))

        if save:
            to_set = {"bucket": bucket}
            # 안전하게 동기화(이미 백필했지만 혹시 누락 대비)
            addr = doc.get("address") or {}
            if (doc.get("location") or addr.get("location")):
                to_set["location"] = (doc.get("location") or addr.get("location")).strip()
            if (doc.get("district") or addr.get("district")):
                to_set["district"] = (doc.get("district") or addr.get("district")).strip()
            col.update_one({"_id": doc["_id"]}, {"$set": to_set})

    # ===== (3) 통계/로그 =====
    total = len(results)
    counter = Counter([b for _, _, b in results])
    classified = total - counter.get("etc", 0)

    print(f"[TOTAL SCANNED] {total}")
    print(f"[CLASSIFIED] {classified}")
    print("[COUNT BY BUCKET]")
    for b, c in counter.most_common():
        print(f"- {b}: {c}")

    print("\n[CLASSIFIED — ALL]")
    for rid, title, bucket in results:
        if bucket != "etc":
            print(f"{rid} | {title} -> {bucket} (rule)")

    if counter.get("etc", 0) > 0:
        print(f"\n[ETC] {counter['etc']}")
        for rid, title, bucket in results:
            if bucket == "etc":
                print(f"{rid} | {title} -> etc")

    # ===== (4) 최상위 위치 필드가 실제로 생겼는지 최종 확인 =====
    has_loc = col.count_documents({"location":{"$type":"string", "$ne":""}})
    has_dist = col.count_documents({"district":{"$type":"string", "$ne":""}})
    one = col.find_one({"location":{"$type":"string"}}, {"_id":1,"address":1,"location":1,"district":1})
    print(f"[VERIFY] has location: {has_loc}, has district: {has_dist}")
    print("[VERIFY] sample doc:", one)

if __name__ == "__main__":
    # save=True 로 실행하면 bucket/위치 필드가 DB에 저장됨
    main(limit=None, save=True)
