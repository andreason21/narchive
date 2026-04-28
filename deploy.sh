#!/bin/bash
# Cloud Run 배포 스크립트
# 사용법: 
#   export GCP_PROJECT_ID=your-project-id
#   bash deploy.sh

set -e

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID 환경변수 설정 필요}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-personal-llm-demo}"
REPO_NAME="${REPO_NAME:-demo-repo}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest"

echo "▶ 프로젝트: $PROJECT_ID / 리전: $REGION"

# 1. 필수 API 활성화
echo "▶ GCP API 활성화..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  --project="$PROJECT_ID"

# 2. Artifact Registry 저장소 (없으면 생성)
if ! gcloud artifacts repositories describe "$REPO_NAME" \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  echo "▶ Artifact Registry 저장소 생성..."
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID"
fi

# 3. Firestore (Native mode) — 최초 1회만
echo "▶ Firestore 확인 (없으면 생성됨)..."
gcloud firestore databases create \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --type=firestore-native 2>/dev/null || echo "  (이미 존재)"

# 4. Vector index 생성 안내
cat <<EOF

⚠️  Firestore Vector Index를 수동으로 생성해야 합니다 (최초 1회):

gcloud firestore indexes composite create \\
  --collection-group=entries \\
  --query-scope=COLLECTION \\
  --field-config=field-path=user_id,order=ASCENDING \\
  --field-config=vector-config='{"dimension":"768","flat":"{}"}',field-path=embedding \\
  --project=$PROJECT_ID

또는 처음 vector_search 호출 시 에러 메시지의 링크를 따라 생성하세요.

EOF

# 5. 빌드 & 배포
echo "▶ Cloud Build로 이미지 빌드..."
gcloud builds submit . \
  --tag="$IMAGE" \
  --project="$PROJECT_ID"

echo "▶ Cloud Run 배포..."
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --memory=1Gi \
  --cpu=1 \
  --timeout=300 \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION}" \
  --project="$PROJECT_ID"

URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')
echo ""
echo "✅ 배포 완료!"
echo "🔗 URL: $URL"
echo ""
echo "📱 모바일에서 위 URL을 열고 마이크 권한을 허용하세요."
