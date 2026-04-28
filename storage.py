"""
Firestore 저장소 서비스
- entries: 모든 캡처 데이터 (음성 일기, 결정 로그, 인터뷰 답변)
- spine: 추출된 Decision Spine 문서
- Vector search로 RAG retrieval 수행
"""
import os
import time
import uuid
from typing import List, Optional
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
DB = firestore.Client(project=PROJECT_ID)

ENTRIES_COL = "entries"
SPINE_COL = "spine"


def save_entry(
    user_id: str,
    entry_type: str,  # "voice_journal" | "decision_log" | "interview_answer"
    text: str,
    embedding: List[float],
    metadata: Optional[dict] = None,
) -> str:
    """캡처 데이터를 임베딩과 함께 저장."""
    entry_id = str(uuid.uuid4())
    doc_ref = DB.collection(ENTRIES_COL).document(entry_id)
    doc_ref.set(
        {
            "user_id": user_id,
            "type": entry_type,
            "text": text,
            "embedding": Vector(embedding),
            "metadata": metadata or {},
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_at_ts": int(time.time()),
        }
    )
    return entry_id


def list_entries(user_id: str, limit: int = 50) -> List[dict]:
    """사용자의 모든 entry를 최신순으로."""
    query = (
        DB.collection(ENTRIES_COL)
        .where(filter=firestore.FieldFilter("user_id", "==", user_id))
        .order_by("created_at_ts", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    results = []
    for doc in query.stream():
        d = doc.to_dict()
        results.append(
            {
                "id": doc.id,
                "type": d.get("type"),
                "text": d.get("text"),
                "metadata": d.get("metadata", {}),
                "created_at_ts": d.get("created_at_ts"),
            }
        )
    return results


def vector_search(
    user_id: str, query_embedding: List[float], k: int = 5
) -> List[dict]:
    """RAG: 쿼리와 의미적으로 가까운 entry들 검색."""
    base_query = DB.collection(ENTRIES_COL).where(
        filter=firestore.FieldFilter("user_id", "==", user_id)
    )
    vector_query = base_query.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_embedding),
        distance_measure=DistanceMeasure.COSINE,
        limit=k,
    )
    results = []
    for doc in vector_query.stream():
        d = doc.to_dict()
        results.append(
            {
                "id": doc.id,
                "type": d.get("type"),
                "text": d.get("text"),
                "created_at_ts": d.get("created_at_ts"),
            }
        )
    return results


def save_spine(user_id: str, spine_text: str) -> None:
    """Decision Spine 문서 저장 (사용자당 1개, 덮어쓰기)."""
    DB.collection(SPINE_COL).document(user_id).set(
        {
            "user_id": user_id,
            "text": spine_text,
            "updated_at": firestore.SERVER_TIMESTAMP,
            "updated_at_ts": int(time.time()),
        }
    )


def get_spine(user_id: str) -> Optional[str]:
    """저장된 Spine 가져오기."""
    doc = DB.collection(SPINE_COL).document(user_id).get()
    if doc.exists:
        return doc.to_dict().get("text")
    return None


def delete_entry(entry_id: str) -> None:
    DB.collection(ENTRIES_COL).document(entry_id).delete()
