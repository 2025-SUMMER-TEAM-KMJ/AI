# main.py
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from chromadb import Client
import chromadb.config
import re

from where_minimal import build_where_from_llm

# ===== MongoDB =====
client = MongoClient("mongodb://root:root@35.192.157.46:27017/?authSource=admin")
db = client["db"]
collection = db["master_job_postings"]

# ===== Chroma =====
vc_client = Client()
vc_collection = vc_client.get_or_create_collection("master_job_postings")

# ===== 유틸 =====
def pick_address(doc):
    a = doc.get("address") or {}
    if isinstance(a, dict) and any(a.values()):
        return a
    ca = (doc.get("company") or {}).get("address") or {}
    return ca if isinstance(ca, dict) else {}

def extract_sido(full_location: str) -> str:
    if not full_location: return ""
    m = re.match(r"^(\S+?시|\S+?도)", full_location)
    return (m.group(1) if m else full_location.split()[0]).strip()

def extract_sigungu(full_location: str) -> str:
    if not full_location: return ""
    parts = full_location.split()
    return (parts[1] if len(parts) > 1 else "").strip()

def norm_sido(s: str) -> str:
    s = (s or "").strip()
    table = {
        "서울특별시":"서울","서울시":"서울",
        "부산광역시":"부산","부산시":"부산",
        "대구광역시":"대구","대구시":"대구",
        "인천광역시":"인천","인천시":"인천",
        "광주광역시":"광주","광주시":"광주",
        "대전광역시":"대전","대전시":"대전",
        "울산광역시":"울산","울산시":"울산",
        "세종특별자치시":"세종","세종시":"세종",
        "경기도":"경기",
    }
    return table.get(s, s)

# ===== 데이터 로드 =====
raw_docs = list(collection.find({}, {
    "_id": 1,
    "company.name": 1,
    "company.address": 1,
    "company.avgSalary": 1,
    "company.avgEntrySalary": 1,
    "address": 1,
    "detail.position": 1,
    "detail.main_tasks": 1,
    "detail.requirements": 1,
    "detail.preferred_points": 1,
    "avgSalary": 1,
    "avgEntrySalary": 1,
    "bucket": 1,
    "externalUrl": 1,
}))

# ===== 텍스트/메타 생성 =====
texts, ids, metadatas = [], [], []

for doc in raw_docs:
    _id = str(doc.get("_id"))
    company = doc.get("company") or {}
    detail = doc.get("detail") or {}
    position = detail.get("position") or {}

    company_name = (company.get("name") or "").strip()

    addr = pick_address(doc)
    location = (addr.get("location") or "").strip()
    district = (addr.get("district") or "").strip()
    full_location = (addr.get("full_location") or "").strip()

    if not location and full_location:
        location = extract_sido(full_location)
    if not district and full_location:
        district = extract_sigungu(full_location)

    location = norm_sido(location)

    job_list = position.get("job", [])
    job_value = ", ".join(job_list) if isinstance(job_list, list) else (job_list or "")
    job_group = (position.get("jobGroup") or "").strip()

    job_group = (position.get("jobGroup") or "").strip()

    salary = (
        doc.get("avgSalary")
        or company.get("avgSalary")
        or doc.get("avgEntrySalary")
        or company.get("avgEntrySalary")
    )
    salary_text = salary if salary not in (None, "") else "정보 없음"

    content = "\n\n".join([
        f"회사명: {company_name}",
        f"지역: {full_location or (location + ' ' + district)}",
        f"평균 연봉: {salary_text}",
        f"직무와 직군: {job_value} {job_group}",
        f"주요 업무: {(detail.get('main_tasks') or '').strip()}",
        f"자격 요건: {(detail.get('requirements') or '').strip()}",
        f"우대 사항: {(detail.get('preferred_points') or '').strip()}",
        f"버킷: {(doc.get('bucket') or '정보 없음')}",
        f"URL: {doc.get('externalUrl') or ''}",
    ]).strip()


    texts.append(content)
    ids.append(_id)

    meta = {}
    if company_name: meta["company"] = company_name
    if location:     meta["location"] = location
    if district:     meta["district"] = district
    if job_value:    meta["job"] = job_value
    if job_group:    meta["job_group"] = job_group
    if doc.get("bucket"): meta["bucket"] = (doc.get("bucket") or "").strip()
    metadatas.append(meta)

# ===== 임베딩 & 업서트 =====
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
embeddings = model.encode(texts).tolist()

vc_collection.add(
    documents=texts,
    ids=ids,
    embeddings=embeddings,
    metadatas=metadatas
)

# ===== 간단 쿼리 =====
query = "테헤란로 백엔드 공고 알려줘"
qe = model.encode([query]).tolist()
where_cond = build_where_from_llm(query) or {}

res = vc_collection.query(
    query_embeddings=qe,
    n_results=3,
    include=["documents", "metadatas"],
    where=where_cond if where_cond else None
)

for i, (doc, meta) in enumerate(zip(res.get("documents", [[]])[0], res.get("metadatas", [[]])[0]), 1):
    print(f"\nResult #{i}\n{doc}\nMetadata:", meta)
