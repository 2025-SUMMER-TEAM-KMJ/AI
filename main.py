# main2.py (청크 인덱싱 + where_minimal 사용 + 점수기반 질의; 반환은 job_id 리스트)
from __future__ import annotations

from typing import List, Dict, Any, Tuple
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from chromadb import Client
import chromadb.config
import re
import numpy as np
from where_minimal import build_where_from_llm

# ── 설정(전역 상수) ──
MAX_CHARS = 1100
OVERLAP_CHARS = 150
INDEX_IF_EMPTY_ONLY = True  # True면 컬렉션 비어있을 때만 인덱싱, False면 매 실행마다 add

# ── Mongo/Chroma ──
client = MongoClient("mongodb://root:root@35.192.157.46:27017/?authSource=admin")
db = client["db"]
collection = db["master_job_postings"]

vc_client = Client()
vc_collection = vc_client.get_or_create_collection(
    "master_job_postings",
    metadata={"hnsw:space": "cosine"}
)

# ── 주소 유틸 ──
def pick_address(doc: Dict[str, Any]) -> Dict[str, Any]:
    a = doc.get("address") or {}
    if isinstance(a, dict) and any(a.values()):
        return a
    ca = (doc.get("company") or {}).get("address") or {}
    return ca if isinstance(ca, dict) else {}

def extract_sido(full_location: str) -> str:
    if not full_location:
        return ""
    m = re.match(r"^(\S+?시|\S+?도)", full_location)
    return (m.group(1) if m else full_location.split()[0]).strip()

def extract_sigungu(full_location: str) -> str:
    if not full_location:
        return ""
    parts = full_location.split()
    return (parts[1] if len(parts) > 1 else "").strip()

def norm_sido(s: str) -> str:
    s = (s or "").strip()
    table = {
        "서울특별시": "서울", "서울시": "서울",
        "부산광역시": "부산", "부산시": "부산",
        "대구광역시": "대구", "대구시": "대구",
        "인천광역시": "인천", "인천시": "인천",
        "광주광역시": "광주", "광주시": "광주",
        "대전광역시": "대전", "대전시": "대전",
        "울산광역시": "울산", "울산시": "울산",
        "세종특별자치시": "세종", "세종시": "세종",
        "경기도": "경기",
    }
    return table.get(s, s)

# ── 데이터 로드 ──
raw_docs = list(collection.find({}, {
    "_id": 1,
    "company.name": 1,
    "company.address": 1,
    "company.avgSalary": 1,
    "company.avgEntrySalary": 1,
    "address": 1,
    "detail.position": 1,
    "detail.intro": 1,
    "detail.main_tasks": 1,
    "detail.requirements": 1,
    "detail.preferred_points": 1,
    "detail.benefits": 1,
    "avgSalary": 1,
    "avgEntrySalary": 1,
    "bucket": 1,
    "externalUrl": 1,
    "salary_bucket_2m_label": 1,
}))

# ── 문서 → 텍스트/메타 ──
def build_blocks_and_meta(doc: Dict[str, Any]) -> Tuple[list, dict]:
    company = doc.get("company") or {}
    detail = doc.get("detail") or {}
    position = detail.get("position") or {}

    company_name = (company.get("name") or "").strip()

    addr = pick_address(doc)
    location = (addr.get("location") or "").strip()
    district = (addr.get("district") or "").strip()
    full_location = (addr.get("full_location") or "").strip()

    intro    = (detail.get("intro") or "").strip()
    benefits = (detail.get("benefits") or "").strip()

    if not location and full_location:
        location = extract_sido(full_location)
    if not district and full_location:
        district = extract_sigungu(full_location)
    location = norm_sido(location)

    job_list = position.get("job", [])
    job_value = ", ".join(job_list) if isinstance(job_list, list) else (job_list or "")
    job_group = (position.get("jobGroup") or "").strip()

    salary = (
        doc.get("avgSalary")
        or company.get("avgSalary")
        or doc.get("avgEntrySalary")
        or company.get("avgEntrySalary")
    )
    salary_text = salary if salary not in (None, "") else "정보 없음"

    sal_bucket_label = doc.get("salary_bucket_2m_label") or ""

    blocks = [
        f"회사명: {company_name}",
        f"지역: {full_location or (location + ' ' + district)}",
        f"평균 연봉: {salary_text}",
        f"연봉 버킷(200만): {doc.get('salary_bucket_2m_label') or '정보 없음'}",
        f"직무와 직군: {job_value} {job_group}",
        f"소개: {intro}",
        f"주요 업무: {(detail.get('main_tasks') or '').strip()}",
        f"자격 요건: {(detail.get('requirements') or '').strip()}",
        f"우대 사항: {(detail.get('preferred_points') or '').strip()}",
        f"복지: {benefits}",
        f"버킷: {(doc.get('bucket') or '정보 없음')}",
        f"URL: {doc.get('externalUrl') or ''}",
    ]

    meta: Dict[str, Any] = {}
    if company_name: meta["company"] = company_name
    if location:     meta["location"] = location
    if district:     meta["district"] = district
    if job_value:    meta["job"] = job_value
    if job_group:    meta["job_group"] = job_group
    if doc.get("bucket"): meta["bucket"] = (doc.get("bucket") or "").strip()
    if sal_bucket_label: meta["salary_bucket_2m_label"] = sal_bucket_label

    return blocks, meta

# ── 문단 기반 청킹 ──
def chunk_by_paragraph_blocks(blocks: list, max_chars=MAX_CHARS, overlap_chars=OVERLAP_CHARS) -> list:
    chunks, cur = [], ""
    for b in blocks:
        add_len = (2 if cur else 0) + len(b)
        if len(cur) + add_len <= max_chars:
            cur = (cur + ("\n\n" if cur else "") + b)
        else:
            if cur:
                chunks.append(cur)
                tail = cur[-overlap_chars:] if overlap_chars > 0 else ""
                cur = tail + ("\n\n" if tail else "") + b
            else:
                chunks.append(b); cur = ""
    if cur:
        chunks.append(cur)
    return chunks

# ── 전문 복원(필요 시 사용 가능) ──
def stitch_chunks(pairs, overlap_chars=OVERLAP_CHARS) -> str:
    if not pairs:
        return ""
    stitched = pairs[0][1] or ""
    for i in range(1, len(pairs)):
        prev = pairs[i - 1][1] or ""
        curr = pairs[i][1] or ""
        if overlap_chars > 0 and len(prev) >= overlap_chars and curr.startswith(prev[-overlap_chars:]):
            stitched += curr[overlap_chars:]
        else:
            if stitched and not stitched.endswith("\n"):
                stitched += "\n"
            stitched += "\n" + curr
    return stitched

# ── 인덱싱(청크 단위 저장) ──
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

def _collection_empty(c) -> bool:
    try:
        got = c.get(include=["ids"], limit=1)
        return len(got.get("ids", [])) == 0
    except Exception:
        return True

if (not INDEX_IF_EMPTY_ONLY) or _collection_empty(vc_collection):
    chunk_docs, chunk_ids, chunk_metas = [], [], []
    for d in raw_docs:
        _id = str(d["_id"])
        blocks, meta = build_blocks_and_meta(d)
        chunks = chunk_by_paragraph_blocks(blocks, max_chars=MAX_CHARS, overlap_chars=OVERLAP_CHARS)
        for i, ch in enumerate(chunks):
            chunk_docs.append(ch)
            chunk_ids.append(f"{_id}::c{i}")
            cm = dict(meta); cm["source_id"] = _id; cm["chunk"] = i
            chunk_metas.append(cm)

    if chunk_docs:
        embeddings = model.encode(chunk_docs).tolist()
        vc_collection.add(documents=chunk_docs, ids=chunk_ids, embeddings=embeddings, metadatas=chunk_metas)

# ── (1) 모든 청크(필요 시) ──
def _get_all_chunks(source_id: str):
    got = vc_collection.get(
        where={"source_id": source_id},
        include=["documents", "metadatas"]
    )
    docs  = got.get("documents", [])
    metas = got.get("metadatas", [])
    pairs = []
    for d, m in zip(docs, metas):
        try:
            idx = int(m.get("chunk", 0))
        except Exception:
            idx = 0
        pairs.append((idx, d, m))
    pairs.sort(key=lambda x: x[0])
    return pairs

# ── (2) 대표 청크(c0)(필요 시) ──
def _get_head_chunk(source_id: str):
    got = vc_collection.get(
        ids=[f"{source_id}::c0"],
        include=["documents", "metadatas"]
    )
    docs  = got.get("documents", [])
    metas = got.get("metadatas", [])
    return (docs[0] if docs else None), (metas[0] if metas else {})

# ── (공통) L2 정규화 ──
def _l2norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, ord=2, axis=-1, keepdims=True) + 1e-12
    return v / n

# ── score 기반 통일 쿼리 (코사인 유사도 직접 계산) ──
def query_with_scores(
    collection,
    query_text: str,
    encoder,                      # SentenceTransformer
    where: dict | None = None,
    n_results: int = 50,
) -> list:
    q = np.asarray(encoder.encode([query_text]))
    q = _l2norm(q)[0]

    raw = collection.query(
        query_embeddings=q.reshape(1, -1).tolist(),
        n_results=n_results,
        include=["documents", "metadatas", "embeddings"],
        **({"where": where} if where else {})
    )

    docs   = raw.get("documents", [[]])[0]
    metas  = raw.get("metadatas", [[]])[0]
    embs   = raw.get("embeddings", [[]])[0]
    if not docs:
        return []

    E = _l2norm(np.asarray(embs))
    scores = (E @ q)

    items = [{"doc": d, "meta": m, "score": float(s)}
             for d, m, s in zip(docs, metas, scores)]
    items.sort(key=lambda x: x["score"], reverse=True)
    return items

# ── (3) search: 상위 문서의 job_id(source_id)만 반환 ──
def search(query: str,
           top_k: int = 3) -> List[str]:
    """
    입력 query로 검색하고, score 기준 상위 문서의 job_id(source_id)만 반환.
    """
    where_cond = build_where_from_llm(query) or None

    items = query_with_scores(
        collection=vc_collection,
        query_text=query,
        encoder=model,
        where=where_cond,
        n_results=max(top_k * 5, 50),
    )

    # 문서 단위 최고 점수만 유지
    best_by_source: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    for it in items:
        meta = it["meta"] or {}
        sid = meta.get("source_id")
        if not sid:
            continue
        sc = it["score"]
        if (sid not in best_by_source) or (sc > best_by_source[sid][0]):
            best_by_source[sid] = (sc, meta)

    ranked = sorted(best_by_source.items(), key=lambda x: x[1][0], reverse=True)[:top_k]
    job_ids = [sid for sid, _ in ranked]
    return job_ids

# ── 실행 예시 ──
if __name__ == "__main__":
    # 예시: 상위 3개의 job_id만 출력(출력은 여기서만; 함수 내부는 반환만 함)
    result_job_ids = search(
        "자율 출퇴근 가능한 회사 알려줘",
        top_k=3,
    )
    print(result_job_ids)
    # 필요 시 여기서만 출력/로그 활용 가능
    # print(result_job_ids)
