# main.py (청크 인덱싱 + where_minimal 사용 + 전문 복원/전체 청크 보기)
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from chromadb import Client
import chromadb.config
import re
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
def pick_address(doc):
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
def build_blocks_and_meta(doc):
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

    # 연봉 폴백: 문서→회사→엔트리
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

    meta = {}
    if company_name: meta["company"] = company_name
    if location:     meta["location"] = location
    if district:     meta["district"] = district
    if job_value:    meta["job"] = job_value
    if job_group:    meta["job_group"] = job_group
    if doc.get("bucket"): meta["bucket"] = (doc.get("bucket") or "").strip()
    if sal_bucket_label: meta["salary_bucket_2m_label"] = sal_bucket_label

    return blocks, meta

# ── 문단 기반 청킹 ──
def chunk_by_paragraph_blocks(blocks, max_chars=MAX_CHARS, overlap_chars=OVERLAP_CHARS):
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

# ── 전문 복원: 청크 이어 붙이며 오버랩 제거 ──
def stitch_chunks(pairs, overlap_chars=OVERLAP_CHARS) -> str:
    """
    pairs: [(idx, ch_doc, ch_meta), ...]  idx 오름차순 정렬 가정
    """
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
        # 일부 드라이버에선 count()가 느릴 수 있어 n_results=1로 질의
        got = c.get(include=["ids"], limit=1)
        return len(got.get("ids", [])) == 0
    except Exception:
        return True  # 실패하면 비었다고 보고 최초 인덱싱 진행

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
        print(f"[INDEX] added chunks: {len(chunk_docs)}")
    else:
        print("[INDEX] nothing to add")
else:
    print("[INDEX] skipped (collection not empty)")

# ── (1) 모든 청크 가져오기 ──
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

# ── (2) 대표 청크(c0)만 가져오기 ──
def _get_head_chunk(source_id: str):
    got = vc_collection.get(
        ids=[f"{source_id}::c0"],
        include=["documents", "metadatas"]
    )
    docs  = got.get("documents", [])
    metas = got.get("metadatas", [])
    return (docs[0] if docs else None), (metas[0] if metas else {})

# ── (3) search 함수: view='stitched' | 'chunks' ──
def search(query: str,
           top_k: int = 3,
           show_all_chunks: bool = False,
           view: str = "chunks",
           per_source_limit: int | None = None,
           truncate_chars: int | None = None):
    qe = model.encode([query]).tolist()
    where_cond = build_where_from_llm(query) or None

    raw = vc_collection.query(
        query_embeddings=qe,
        n_results=max(top_k * 5, 50),
        include=["documents", "metadatas", "distances"],
        **({"where": where_cond} if where_cond else {})
    )

    print("WHERE:", where_cond)

    docs  = raw.get("documents", [[]])[0]
    metas = raw.get("metadatas", [[]])[0]
    dists = raw.get("distances", [[]])[0]

    # 소스(문서) 단위로 베스트 청크를 잡아 문서 랭킹
    best_by_source = {}
    for doc, meta, dist in zip(docs, metas, dists):
        sid = meta.get("source_id")
        if not sid:
            continue
        if sid not in best_by_source or dist < best_by_source[sid][0]:
            best_by_source[sid] = (dist, meta)

    ranked = sorted(best_by_source.items(), key=lambda x: x[1][0])[:top_k]

    for rank, (sid, (dist, _meta)) in enumerate(ranked, 1):
        if show_all_chunks:
            all_pairs = _get_all_chunks(sid)  # [(idx, ch_doc, ch_meta), ...] idx 오름차순
            print(f"\n=== Result #{rank} (distance={dist:.4f}) — source_id={sid} / {len(all_pairs)} chunks ===")

            if view == "stitched":
                # 전문 복원
                fulltext = stitch_chunks(all_pairs, overlap_chars=OVERLAP_CHARS)
                if truncate_chars is not None and len(fulltext) > truncate_chars:
                    fulltext = fulltext[:truncate_chars] + "…"
                print(fulltext)
                # 대표 메타 한 번만
                if all_pairs:
                    print("Metadata:", all_pairs[0][2])
            else:
                # 청크 나열 모드
                pairs_to_show = all_pairs if per_source_limit is None else all_pairs[:per_source_limit]
                for idx, ch_doc, ch_meta in pairs_to_show:
                    body = ch_doc
                    if truncate_chars is not None and len(body) > truncate_chars:
                        body = body[:truncate_chars] + "…"
                    print(f"\n--- Chunk c{idx} ---")
                    print(body)
                    print("Metadata:", ch_meta)
        else:
            head_doc, head_meta = _get_head_chunk(sid)
            out_doc  = head_doc if head_doc else "(no c0)"
            out_meta = head_meta if head_doc else _meta
            print(f"\nResult #{rank} (distance={dist:.4f})")
            print(out_doc)
            print("Metadata:", out_meta)

# ── 실행 예시 ──
if __name__ == "__main__":
    search(
        " 자율 출퇴근할 수 있는 회사 알고 싶어?",
        top_k=3,
        show_all_chunks=True,     # ← 문서별 모든 청크
        view="stitched",          # ← 오버랩 제거하여 전문 복원
        # per_source_limit=None,  # ← 청크 나열 모드에서 문서당 최대 청크 수
        # truncate_chars=None,    # ← 화면이 너무 길면 자르기
    )
