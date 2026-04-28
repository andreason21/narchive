"""
Vertex AI Gemini 통합 서비스
- 음성 transcription (Gemini multimodal)
- 텍스트 임베딩
- 채팅 (인터뷰 / Ask Me)
- Spine 추출
"""
import os
import base64
from typing import AsyncIterator, List
from google import genai
from google.genai import types

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

# 모델 (배포 시점에 최신으로 교체 가능)
MODEL_FAST = os.environ.get("MODEL_FAST", "gemini-2.5-flash")
MODEL_PRO = os.environ.get("MODEL_PRO", "gemini-2.5-pro")
MODEL_EMBED = os.environ.get("MODEL_EMBED", "text-embedding-004")

# Vertex AI 클라이언트 (Cloud Run에서 자동 ADC 사용)
_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Gemini multimodal로 음성을 텍스트로 변환. 한국어/영어 모두 지원."""
    response = _client.models.generate_content(
        model=MODEL_FAST,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            "이 음성을 정확하게 텍스트로 변환해줘. 한국어와 영어 모두 원래 언어 그대로 유지하고, "
            "문장부호와 단락 구분도 자연스럽게 넣어줘. 변환된 텍스트만 출력하고 다른 설명은 하지 마.",
        ],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    return response.text.strip()


def embed_text(text: str) -> List[float]:
    """텍스트를 벡터로 임베딩 (RAG 검색용)."""
    result = _client.models.embed_content(
        model=MODEL_EMBED,
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    return result.embeddings[0].values


def embed_query(text: str) -> List[float]:
    """검색 쿼리용 임베딩 (RETRIEVAL_QUERY 모드)."""
    result = _client.models.embed_content(
        model=MODEL_EMBED,
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return result.embeddings[0].values


async def chat(
    system_prompt: str,
    messages: List[dict],
    use_pro: bool = False,
    temperature: float = 0.7,
) -> str:
    """채팅 응답 (인터뷰 진행, Ask Me 응답)."""
    model = MODEL_PRO if use_pro else MODEL_FAST
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    response = _client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
        ),
    )
    return response.text


async def chat_stream(
    system_prompt: str,
    messages: List[dict],
    use_pro: bool = False,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """스트리밍 채팅 응답."""
    model = MODEL_PRO if use_pro else MODEL_FAST
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    stream = _client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
        ),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text
