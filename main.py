from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from chromadb import Client
import chromadb.config

# MongoDB 연결
client = MongoClient("mongodb://root:root@35.192.157.46:27017/?authSource=admin")
db = client["db"]
collection = db["master_job_postings"]

# Chroma 클라이언트 생성
vc_client = Client()
vc_collection = vc_client.get_or_create_collection("master_job_postings")

# MongoDB에서 문서 로드
raw_docs = list(collection.find({}, {
    "_id": 1, "detail": 1, "company": 1, "address": 1,
    "externalUrl": 1, "metadata": 1,
    "avgSalary": 1, "features": 1, "skill_tags": 1
}).limit(100))

print(f"{len(raw_docs)}개 채용공고 로드됨")

# 텍스트 및 ID 추출
texts = []
ids = []

for doc in raw_docs:
    mongo_id = str(doc.get("_id"))

    company = doc.get("company", {})
    detail = doc.get("detail", {})
    position = detail.get("position", {})
    address = doc.get("address", {})

    company_name = company.get("name", "")
    location = address.get("location", "")
    district = address.get("district", "")
    full_location = address.get("full_location", "")
    avg_salary = doc.get("avgSalary", "")
    main_tasks = detail.get("main_tasks", "")
    requirements = detail.get("requirements", "")
    preferred_points = detail.get("preferred_points", "")
    job_list = position.get("job", [])
    job_value = ", ".join(job_list) if isinstance(job_list, list) else job_list
    job_group = position.get("jobGroup", "")

    content = "\n\n".join([
        f"회사명: {company_name}",
        f"지역: {full_location or (location + ' ' + district)}",
        f"평균 연봉: {avg_salary if avg_salary else '정보 없음'}",
        f"직무와 직군: {job_value} {job_group}",
        f"주요 업무: {main_tasks}",
        f"자격 요건: {requirements}",
        f"우대 사항: {preferred_points}"
    ]).strip()

    texts.append(content)
    ids.append(mongo_id)

# SentenceTransformer로 임베딩
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
embeddings = model.encode(texts).tolist()

# Chroma에 벡터와 함께 저장
vc_collection.add(
    documents=texts,
    ids=ids,
    embeddings=embeddings
)

print("Chroma DB에 문서 저장 완료")

# 쿼리 예시
query = "코리아포트원 채용 공고"
query_embedding = model.encode([query]).tolist()

result = vc_collection.query(
    query_embeddings=query_embedding,
    n_results=3,
    include=["documents"]
)

# 결과 출력
print("\n검색 결과:")
for i, doc in enumerate(result["documents"][0]):
    print(f"\n🔹 Result #{i+1}")
    print(doc)
