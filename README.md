# 나처럼 생각하는 LLM — GCP 데모

스마트폰에서 음성/텍스트로 캡처한 데이터를 GCP에 쌓고, Decision Spine + RAG로 너처럼 답하는 LLM을 데모하는 풀 파이프라인.

## 데모 흐름

```
[모바일 PWA]
   ↓  음성 일기 / 결정 로그 / AI 인터뷰
[Cloud Run (FastAPI)]
   ↓  Gemini로 transcribe → embedding
[Firestore + Vector Search]
   ↓  Decision Spine 자동 추출
[Ask Me 탭]
   질문 → RAG 검색 → Spine 결합 → Gemini Pro로 너처럼 답변
```

## 아키텍처

| 역할 | GCP 서비스 |
|------|----------|
| 백엔드 + 프론트 | Cloud Run (단일 컨테이너) |
| 데이터 저장 | Firestore (Native, vector search 내장) |
| 음성 → 텍스트 | Vertex AI Gemini 2.5 Flash (multimodal) |
| 임베딩 | Vertex AI text-embedding-004 |
| Spine 추출 / Ask Me | Vertex AI Gemini 2.5 Pro |
| 컨테이너 빌드 | Cloud Build |

## 사전 준비

- `gcloud` CLI 설치 및 로그인 (`gcloud auth login`)
- GCP 프로젝트 생성, **결제 연결 필수** (Vertex AI는 결제 계정 필요)
- 프로젝트에 `Owner` 또는 충분한 권한

## 빠른 배포 (3단계)

```bash
# 1. 환경변수
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-central1   # asia-northeast3(서울)도 가능

# 2. 코드 준비
git clone <this-repo>   # 또는 폴더로 복사
cd personal-llm-demo

# 3. 배포
bash deploy.sh
```

배포가 끝나면 Cloud Run URL을 출력해. 이 URL을 폰 브라우저에서 열고 **마이크 권한 허용**하면 데모 시작.

## Vector Index 생성 (필수, 최초 1회)

`Ask Me` 첫 호출에서 vector search 인덱스가 없으면 에러가 나는데, 에러 메시지에 인덱스 생성 링크가 포함돼. 그걸 클릭하거나, 다음 명령으로 미리 만들어:

```bash
gcloud firestore indexes composite create \
  --collection-group=entries \
  --query-scope=COLLECTION \
  --field-config=field-path=user_id,order=ASCENDING \
  --field-config='vector-config={"dimension":"768","flat":"{}"},field-path=embedding' \
  --project=$GCP_PROJECT_ID
```

인덱스 생성에 5-10분 걸려.

## 데모 시나리오 (3분 압축)

1. **Capture 탭** — 음성 버튼 누르고 30초~1분 말하기. "오늘 X 결정에 대해 고민했는데..." 식으로.
2. 텍스트로도 결정 로그 2-3개 추가.
3. **Interview 탭** — AI 인터뷰어가 질문 던짐. 3-5턴 답변. "인터뷰 종료·저장" 누르면 다 저장됨.
4. **Spine 탭** — "Spine 재추출" 클릭. 30초 안에 너의 가치관·휴리스틱 markdown 문서 생성됨.
5. **Ask Me 탭** — "내가 이직 제안 받으면 어떻게 할 것 같아?" 같은 질문. RAG로 관련 기록 가져와서 너처럼 답함. 스트리밍으로 표시.

## 로컬 개발

```bash
cd backend
pip install -r requirements.txt
export GCP_PROJECT_ID=your-project-id
export GCP_LOCATION=us-central1
gcloud auth application-default login   # ADC 셋업
uvicorn main:app --reload --port 8080
```

`http://localhost:8080`에서 확인.

## 비용 가이드 (데모 기준)

데모로 가볍게 쓸 때:
- **Cloud Run**: 거의 무료 (free tier로 충분)
- **Firestore**: 거의 무료 (free tier 50K reads/day)
- **Vertex AI Gemini**:
  - 음성 transcribe (Flash): ~$0.001/분
  - 임베딩: ~$0.0001/캡처
  - Spine 추출 (Pro, 200 entries): ~$0.05/회
  - Ask Me 응답 (Pro): ~$0.01/응답
- **30분 데모 총비용**: 대략 **$0.50 ~ $1**

## 보안 / 프라이버시 주의

이 데모는 **인증 없음**(`--allow-unauthenticated`)이고 단일 사용자(`demo-user`) 고정이야. 프로덕션 가려면:

1. Cloud Run에 `--no-allow-unauthenticated` + Identity-Aware Proxy 또는 Firebase Auth
2. Firestore 보안 규칙으로 user_id 분리
3. 데이터를 클라우드에 두는 것 자체가 싫으면 — 위 코드를 홈서버 (Mac mini + Ollama)에서 자체 호스팅. Gemini 호출 부분만 로컬 LLM으로 교체.
4. PII 마스킹 레이어 추가 (현재는 raw text 저장)

## 모델 교체

`backend/services/llm.py` 상단의 환경변수로 모델 변경 가능:

```bash
# Cloud Run 배포 시
gcloud run services update personal-llm-demo \
  --update-env-vars MODEL_PRO=gemini-2.5-pro,MODEL_FAST=gemini-2.5-flash
```

## 파일 구조

```
personal-llm-demo/
├── backend/
│   ├── main.py                    # FastAPI 라우트
│   ├── services/
│   │   ├── llm.py                 # Vertex AI Gemini (STT, embed, chat)
│   │   ├── storage.py             # Firestore + vector search
│   │   └── spine.py               # Spine 추출 + 인터뷰 프롬프트
│   └── requirements.txt
├── frontend/
│   └── index.html                 # 모바일 PWA (단일 파일)
├── Dockerfile                     # Cloud Run 컨테이너
├── deploy.sh                      # 원샷 배포
└── README.md
```

## 이 데모가 보여주는 것 / 못 보여주는 것

**보여주는 것**:
- 모바일에서 음성/텍스트 캡처 → 클라우드 저장 → 추출 → 개인화 응답의 **end-to-end 루프**
- Stanford식 인터뷰 프로토콜 자동화
- VBN(Value-Belief-Norm) reasoning 기반 응답
- Vector RAG + Spine document 결합 패턴

**못 보여주는 것** (다음 단계):
- 진짜 일관성 검증 (holdout 테스트, drift 모니터링)
- LoRA fine-tuning (데모는 base model + 프롬프팅만)
- On-device PII 마스킹
- Multi-user / 인증
- 장기 메모리 압축 (entry 1000개 넘어가면 Spine 추출 느려짐)
