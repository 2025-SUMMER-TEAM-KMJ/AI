from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from chromadb import Client
import chromadb.config

# where 생성기 임포트
from where_minimal import build_where_from_llm

# MongoDB 연결
client = MongoClient("mongodb://root:root@35.192.157.46:27017/?authSource=admin")
db = client["db"]
collection = db["master_job_postings"]

# Chroma 클라이언트 생성
vc_client = Client()
vc_collection = vc_client.get_or_create_collection("master_job_postings")

# MongoDB에서 문서 로드 (bucket 포함 권장)
raw_docs = list(collection.find({}, {
    "_id": 1, "detail": 1, "company": 1, "address": 1,
    "externalUrl": 1, "metadata": 1,
    "avgSalary": 1, "features": 1, "skill_tags": 1,
    "bucket": 1
}).limit(100))

print(f"{len(raw_docs)}개 채용공고 로드됨")

# 텍스트/ID/메타데이터 추출
texts, ids, metadatas = [], [], []

for doc in raw_docs:
    mongo_id = str(doc.get("_id"))

    company = doc.get("company", {}) or {}
    detail = doc.get("detail", {}) or {}
    position = detail.get("position", {}) or {}
    address = doc.get("address", {}) or {}

    company_name = company.get("name", "")
    location = address.get("location", "")       # 시/도
    district = address.get("district", "")       # 시/군/구
    full_location = address.get("full_location", "")
    avg_salary = doc.get("avgSalary", "")
    main_tasks = detail.get("main_tasks", "")
    requirements = detail.get("requirements", "")
    preferred_points = detail.get("preferred_points", "")
    job_list = position.get("job", [])
    job_value = ", ".join(job_list) if isinstance(job_list, list) else (job_list or "")
    job_group = position.get("jobGroup", "")
    bucket = doc.get("bucket", "")               # 값 없으면 메타에서 키 자체를 빼는 게 안전

    content = "\n\n".join([
        f"회사명: {company_name}",
        f"지역: {full_location or (location + ' ' + district)}",
        f"평균 연봉: {avg_salary if avg_salary else '정보 없음'}",
        f"직무와 직군: {job_value} {job_group}",
        f"주요 업무: {main_tasks}",
        f"자격 요건: {requirements}",
        f"우대 사항: {preferred_points}",
        f"버킷: {bucket if bucket else '정보 없음'}"
    ]).strip()

    texts.append(content)
    ids.append(mongo_id)

    # where가 메타데이터 기준으로만 먹으므로 값 있는 것만 저장
    meta = {}
    if company_name: meta["company"] = company_name
    if location:     meta["location"] = location
    if district:     meta["district"] = district
    if job_value:    meta["job"] = job_value
    if job_group:    meta["job_group"] = job_group
    if bucket:       meta["bucket"] = bucket
    metadatas.append(meta)

# 임베딩
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
embeddings = model.encode(texts).tolist()

# Chroma에 저장 (메타데이터 포함)
vc_collection.add(
    documents=texts,
    ids=ids,
    embeddings=embeddings,
    metadatas=metadatas
)

print("Chroma DB에 문서 저장 완료")

# 쿼리 예시
query = "지금 자바스크립트 공부 중인데 내가 넣어볼만한 채용 공고 알려줘"
query_embedding = model.encode([query]).tolist()

# LLM으로 where 조건 생성
where_cond = build_where_from_llm(query)
print("LLM where 조건:", where_cond)

query_kwargs = {
    "query_embeddings": query_embedding,
    "n_results": 3,
    "include": ["documents", "metadatas"],
}
# 비어있지 않을 때만 where 추가
if where_cond:
    query_kwargs["where"] = where_cond

result = vc_collection.query(**query_kwargs)


# 결과 출력
print("\n검색 결과:")
docs = result.get("documents", [[]])[0]
metas = result.get("metadatas", [[]])[0]
for i, doc in enumerate(docs):
    print(f"\nResult #{i+1}")
    print(doc)
    if i < len(metas):
        print("Metadata:", metas[i])
