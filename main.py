"""
FastAPI 메인 애플리케이션
- /api/* : REST 엔드포인트
- / : 정적 PWA 프론트엔드

데모용 단일 사용자: user_id="demo-user" 고정
프로덕션 시 인증 추가 필요.
"""
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services import llm, storage, spine

DEMO_USER_ID = "demo-user"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="Personal LLM Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Pydantic 모델
# ─────────────────────────────────────────────


class TextCaptureRequest(BaseModel):
    text: str
    entry_type: str = "decision_log"  # voice_journal | decision_log | interview_answer
    metadata: Optional[dict] = None


class InterviewMessage(BaseModel):
    messages: List[dict]  # [{role: "user"|"assistant", content: "..."}]


class AskRequest(BaseModel):
    question: str


class SaveInterviewRequest(BaseModel):
    transcript: List[dict]  # 인터뷰 전체 turn


# ─────────────────────────────────────────────
# 헬스체크
# ─────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok", "user_id": DEMO_USER_ID}


# ─────────────────────────────────────────────
# 캡처 엔드포인트
# ─────────────────────────────────────────────


@app.post("/api/capture/audio")
async def capture_audio(audio: UploadFile = File(...)):
    """음성 파일 → STT → 임베딩 → Firestore 저장."""
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "empty audio")

    mime = audio.content_type or "audio/webm"
    text = await llm.transcribe_audio(audio_bytes, mime_type=mime)

    if not text.strip():
        raise HTTPException(400, "transcription empty")

    embedding = llm.embed_text(text)
    entry_id = storage.save_entry(
        user_id=DEMO_USER_ID,
        entry_type="voice_journal",
        text=text,
        embedding=embedding,
        metadata={"audio_mime": mime, "audio_size": len(audio_bytes)},
    )
    return {"id": entry_id, "text": text, "type": "voice_journal"}


@app.post("/api/capture/text")
async def capture_text(req: TextCaptureRequest):
    """텍스트 직접 입력 (decision log 등)."""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "empty text")
    embedding = llm.embed_text(text)
    entry_id = storage.save_entry(
        user_id=DEMO_USER_ID,
        entry_type=req.entry_type,
        text=text,
        embedding=embedding,
        metadata=req.metadata or {},
    )
    return {"id": entry_id, "text": text, "type": req.entry_type}


@app.get("/api/entries")
async def list_entries(limit: int = 50):
    """저장된 entry들 (최신순)."""
    return {"entries": storage.list_entries(DEMO_USER_ID, limit=limit)}


@app.delete("/api/entries/{entry_id}")
async def delete_entry(entry_id: str):
    storage.delete_entry(entry_id)
    return {"deleted": entry_id}


# ─────────────────────────────────────────────
# 인터뷰 (Stanford식 심층 인터뷰)
# ─────────────────────────────────────────────


@app.post("/api/interview/turn")
async def interview_turn(req: InterviewMessage):
    """인터뷰어가 다음 질문 생성."""
    response = await llm.chat(
        system_prompt=spine.INTERVIEWER_SYSTEM_PROMPT,
        messages=req.messages,
        use_pro=False,
        temperature=0.8,
    )
    return {"response": response}


@app.post("/api/interview/save")
async def save_interview(req: SaveInterviewRequest):
    """인터뷰 종료 시 사용자 답변들을 entry로 저장."""
    saved = []
    for turn in req.transcript:
        if turn.get("role") != "user":
            continue
        content = turn.get("content", "").strip()
        if not content:
            continue
        embedding = llm.embed_text(content)
        entry_id = storage.save_entry(
            user_id=DEMO_USER_ID,
            entry_type="interview_answer",
            text=content,
            embedding=embedding,
            metadata={"context": "interview_session"},
        )
        saved.append(entry_id)
    return {"saved_count": len(saved), "ids": saved}


# ─────────────────────────────────────────────
# Decision Spine 추출
# ─────────────────────────────────────────────


@app.post("/api/spine/extract")
async def extract_spine_endpoint():
    """모든 entry로부터 Decision Spine 재추출."""
    entries = storage.list_entries(DEMO_USER_ID, limit=200)
    spine_text = await spine.extract_spine(entries)
    storage.save_spine(DEMO_USER_ID, spine_text)
    return {"spine": spine_text, "based_on_entries": len(entries)}


@app.get("/api/spine")
async def get_spine_endpoint():
    spine_text = storage.get_spine(DEMO_USER_ID)
    return {"spine": spine_text or ""}


# ─────────────────────────────────────────────
# Ask Me — 너처럼 답하는 LLM (RAG + Spine)
# ─────────────────────────────────────────────


@app.post("/api/ask")
async def ask(req: AskRequest):
    """RAG + Spine으로 사용자처럼 답변 생성 (스트리밍)."""
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "empty question")

    # 1. 쿼리 임베딩 → vector search
    q_embedding = llm.embed_query(question)
    retrieved = storage.vector_search(DEMO_USER_ID, q_embedding, k=5)

    # 2. Spine 가져오기
    spine_text = storage.get_spine(DEMO_USER_ID) or ""

    # 3. 프롬프트 빌드
    system_prompt = spine.build_ask_me_prompt(spine_text, retrieved)

    # 4. 스트리밍 응답
    async def event_stream():
        # 메타데이터 먼저
        yield f"data: {{\"type\":\"meta\",\"retrieved\":{len(retrieved)},\"has_spine\":{str(bool(spine_text)).lower()}}}\n\n"
        try:
            async for chunk in llm.chat_stream(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": question}],
                use_pro=True,
                temperature=0.7,
            ):
                # JSON 안전하게 escape
                escaped = chunk.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
                yield f"data: {{\"type\":\"chunk\",\"text\":\"{escaped}\"}}\n\n"
            yield "data: {\"type\":\"done\"}\n\n"
        except Exception as e:
            yield f"data: {{\"type\":\"error\",\"message\":\"{str(e)}\"}}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────
# 정적 프론트엔드 서빙 (마지막에 마운트)
# ─────────────────────────────────────────────

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
