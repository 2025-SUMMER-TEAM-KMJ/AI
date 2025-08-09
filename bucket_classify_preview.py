# bucket_classify_preview.py
# 목적: 필터링을 위한 직업 분류 버킷 생성
# 단계:
#   1) 직무명(title) 우선 룰 매칭
#   2) 본문 보조 룰(우선순위 기반)
#   3) 둘 다 실패하면 'etc'

import re
from collections import Counter
from typing import Any, Dict, List, Optional
from pymongo import MongoClient

# ====== Mongo 설정 ======
MONGO_URI = "mongodb://root:root@35.192.157.46:27017/?authSource=admin"
DB_NAME = "db"
COLL_NAME = "master_job_postings"

# ====== 1) 직무명(title) 우선 룰 ======
# 주의: 위에서 아래로 매칭. 먼저 매칭되는 버킷이 승리.
TITLE_RULES = [
    # 디자인 (프론트/백엔드 키워드에 새지 않도록 위쪽에)
    ("design", [
        r"\b2d\b|2d\s*디자이너",
        r"ui[,/\s]*gui\s*디자이너|ui\s*디자이너",
        r"ux\s*디자이너|\bux\b\s*디자이너",
        r"웹\s*디자이너|그래픽\s*디자이너|bi/bx\s*디자이너|브랜드\s*디자이너",
        r"제품\s*디자이너|산업\s*디자이너|모션|영상\s*편집|비디오\s*편집",
        r"공간\s*디자이너|인테리어\s*디자이너|출판[,\s]*편집\s*디자이너"
    ]),
    # 보안/인프라
    ("security", [
        r"보안\s*엔지니어|정보보호|security",
        r"시스템.*관리자|네트워크\s*관리자|\bsre\b|\bsoc\b|\bsiem\b"
    ]),
    # 기획/전략/PM/운영
    ("product", [
        r"pm·?po|\bpo\b|product\s*(manager|owner)|프로덕트\s*매니저|서비스\s*기획",
        r"전략\s*기획자?|사업개발|biz\s*dev|\bbd\b|운영\s*매니저|컨설턴트",
        r"교육\s*기획|교재",
        r"\bcio\b|chief\s*information\s*officer"
    ]),
    # 마케팅/PR/로컬라이제이션
    ("marketing", [
        r"\b마케터\b|마케팅|브랜드|콘텐츠\s*마케터|퍼포먼스\s*마케터|\bbtl\b|\bpr\b|홍보",
        r"글로벌\s*마케팅|소셜\s*마케터|키워드\s*광고",
        r"통[·\s]*번역|locali[sz]ation|로컬라이제이션"
    ]),
    # 영업/KAM/MD
    ("sales", [
        r"영업|세일즈|account\s*executive|대면\s*영업",
        r"key\s*account|주요고객사\s*담당자|\bkam\b|유통\s*관리자|리테일\s*md|매장\s*(관리자|점원)|기술영업|해외영업"
    ]),
    # CS/운영/총무/유지보수
    ("cs", [
        r"\bcs\b|고객성공|customer\s*success|고객\s*응대|voc|콜\s*센터|서비스\s*운영|운영\s*매니저|오피스\s*관리|총무|유지보수\s*관리자"
    ]),
    # 데이터 엔지니어/분석 (※ 프론트/백엔드보다 위)
    ("data_engineering", [
        r"데이터\s*엔지니어|data\s*engineer|빅데이터\s*엔지니어|\bdba\b|etl|spark|hadoop|airflow|kafka",
        r"데이터\s*분석가|data\s*analyst"
    ]),
    # AI/ML (※ 프론트/백엔드보다 위)
    ("ai_ml", [
        r"머신러닝|machine\s*learning|\bml\b|딥러닝|deep\s*learning",
        r"\bnlp\b|computer\s*vision|recommendation|mle|데이터\s*사이언티스트|data\s*scientist"
    ]),
    # 프론트엔드/모바일/게임클라/Unity/Unreal
    ("frontend", [
        r"프론트엔드|\bfrontend\b|웹\s*퍼블리셔|\bpublisher\b|ui\s*개발자|프론트\s*(엔드)?",
        r"\breact\b|\bvue\b|\btypescript\b|next\.js\b|svelte\b",
        r"\bios\b|\bandroid\b|모바일\s*개발|react\s*native|flutter",
        r"unity|unreal|게임\s*클라이언트"
    ]),
    # 백엔드/플랫폼/임베디드/QA
    ("backend", [
        r"백엔드|\bbackend\b|서버\s*개발자|\bjava\b|\bspring\b|node\.js|\bnode\b|php|\.net|\bgolang\b|\bgo\b|django|fastapi|nestjs|msa|microservices|자바",
        r"c\+\+|c/c\+\+|임베디드|embedded|erp|sap|oracle",
        r"\bqa\b|테스트\s*엔지니어|품질\s*관리자"
    ]),
    # 법무/라이선스
    ("legal", [r"법무|특허|compliance|준법|계약|라이[센|선]스\s*관리자|\blicense\b"]),
    # 물류/생산/구매
    ("logistics", [r"물류|입·출고|배송|무역\s*사무|수출입|현장\s*소장|구매\s*담당|생산\s*관리자|자재관리"]),
    # HR/회계/재무/헤드헌터
    ("hr", [r"인사|리크루터|헤드헌터|\bhrbp\b|\bhrd\b|평가·보상|회계|경리|재무|자금"]),
]

# ====== 2) 본문 보조 룰 (우선순위 높→낮) ======
BODY_RULES = [
    ("security", [r"보안\s*엔지니어|정보보호|security|\bsre\b|\bsoc\b|\bsiem\b|시스템.*관리자|네트워크\s*관리자"]),
    ("design", [r"\bux\b|ux\s*디자이너|ui[,/\s]*gui\s*디자이너|ui\s*디자이너|그래픽\s*디자이너|bi/bx|브랜딩|웹\s*디자이너|제품\s*디자이너|산업\s*디자이너|모션|영상\s*편집|비디오\s*편집"]),
    ("product", [r"\bpm\b|product\s*(manager|owner)|프로덕트\s*매니저|서비스\s*기획|전략\s*기획|사업개발|교육\s*기획|교재|운영\s*매니저|컨설턴트|\bcio\b"]),
    ("marketing", [r"마케터|마케팅|브랜드|콘텐츠\s*마케터|퍼포먼스\s*마케터|\bpr\b|홍보|로컬라이제이션|통[·\s]*번역|키워드\s*광고|\bbtl\b"]),
    ("sales", [r"영업|세일즈|account\s*executive|key\s*account|\bkam\b|유통\s*관리자|리테일\s*md|매장\s*(관리자|점원)|기술영업|해외영업"]),
    ("cs", [r"\bcs\b|customer\s*success|고객\s*응대|voc|콜\s*센터|서비스\s*운영|운영\s*매니저|오피스\s*관리|총무|유지보수\s*관리자"]),
    ("data_engineering", [r"데이터\s*엔지니어|data\s*engineer|빅데이터|\bdba\b|etl|spark|hadoop|airflow|kafka|데이터\s*분석가|data\s*analyst"]),
    ("ai_ml", [r"머신러닝|machine\s*learning|\bml\b|딥러닝|deep\s*learning|\bnlp\b|computer\s*vision|recommendation|mle|데이터\s*사이언티스트|data\s*scientist"]),
    ("frontend", [r"프론트엔드|\bfrontend\b|웹\s*퍼블리셔|\bpublisher\b|ui\s*개발자|react|vue|typescript|next\.js|svelte|모바일|ios|android|react\s*native|flutter|unity|unreal|게임\s*클라이언트"]),
    ("backend", [r"백엔드|backend|서버\s*개발자|java|spring|node\.js|php|\.net|golang|\bgo\b|django|fastapi|nestjs|msa|microservices|c\+\+|임베디드|embedded|erp|sap|oracle|\bqa\b|테스트\s*엔지니어|품질\s*관리자"]),
    ("legal", [r"법무|특허|compliance|준법|계약|라이[센|선]스"]),
    ("logistics", [r"물류|입·출고|배송|무역\s*사무|수출입|현장\s*소장|구매\s*담당|생산\s*관리자|자재관리"]),
    ("hr", [r"인사|리크루터|헤드헌터|\bhrbp\b|\bhrd\b|평가·보상|회계|경리|재무|자금"]),
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
    # 가능한 경로에서 직무명 추출
    for path in (["job"], ["position","job"], ["detail","position","job"]):
        v = _get(doc, path)
        if isinstance(v, list) and v:
            return str(v[0])
        if isinstance(v, str) and v.strip():
            return v
    # 백업: detail.intro 첫 줄 일부
    intro = _get(doc, ["detail","intro"])
    if isinstance(intro, str) and intro.strip():
        return intro.strip().splitlines()[0][:60]
    return ""

def gather_body(doc: Dict[str, Any]) -> str:
    buf = []
    for path in (["detail","intro"], ["detail","main_tasks"], ["detail","requirements"]):
        v = _get(doc, path)
        if isinstance(v, str) and v.strip():
            buf.append(v)
    body = "\n".join(buf).lower()
    # 과도한 길이 자르기
    return body[:4000]

def match_by_rules(title: str, body: str) -> Optional[str]:
    t = title.lower()

    # 1) 제목 우선
    for bucket, patterns in TITLE_RULES:
        for p in patterns:
            if re.search(p, t, flags=re.IGNORECASE):
                return bucket

    # 2) 본문 보조 (우선순위 반영)
    for bucket, patterns in BODY_RULES:
        for p in patterns:
            if re.search(p, body, flags=re.IGNORECASE):
                return bucket

    return None

def classify_doc(doc: Dict[str, Any]) -> (str, str, str):
    rid = str(doc.get("_id"))
    title = extract_title(doc)
    body = gather_body(doc)
    bucket = match_by_rules(title, body) or "etc"
    return rid, title or "(no-title)", bucket

def main(limit: Optional[int] = None, save: bool = False):
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    col = client[DB_NAME][COLL_NAME]
    cursor = col.find({}, {"_id": 1, "job": 1, "position": 1, "detail": 1}).limit(limit or 0)

    results = []
    for doc in cursor:
        rid, title, bucket = classify_doc(doc)
        results.append((rid, title, bucket))

        if save:
            col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"bucket": bucket}}
            )

    # 통계
    total = len(results)
    counter = Counter([b for _, _, b in results])
    classified = total - counter.get("etc", 0)

    print(f"[TOTAL SCANNED] {total}")
    print(f"[CLASSIFIED] {classified}")
    print("[COUNT BY BUCKET]")
    for b, c in counter.most_common():
        print(f"- {b}: {c}")

    # 전량 출력
    print("\n[CLASSIFIED — ALL]")
    for rid, title, bucket in results:
        if bucket != "etc":
            print(f"{rid} | {title} -> {bucket} (rule)")

    if counter.get("etc", 0) > 0:
        print(f"\n[ETC] {counter['etc']}")
        for rid, title, bucket in results:
            if bucket == "etc":
                print(f"{rid} | {title} -> etc")


if __name__ == "__main__":
    # save=True 로 실행하면 bucket 필드가 DB에 저장됨
    main(limit=None, save=True)
