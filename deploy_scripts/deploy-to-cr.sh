#!/bin/bash

# Load variables from .env file
set -o allexport
source ./.env set
set +o allexport


IFS=',' read -r -a REGION_ARRAY <<< "$REGIONS"

for REGION in "${REGION_ARRAY[@]}"; do
    echo "Deploy region: $region"

    ID=$(uuidgen | tr -d '-' | head -c 8 | tr '[:upper:]' '[:lower:]')
    echo "Generated ID: $ID"

    gcloud builds submit --config deploy_scripts/deploy_cloudbuild_cr.yaml \
      --project "$PROJECT_ID" \
      --substitutions \
        _PROJECT_ID="$PROJECT_ID",_PORT="$SERVER_PORT",_SUB_NAME_PREFIX="$SUB_NAME_PREFIX",_ARTIFACT_REPO="$ARTIFACT_REPO",_REGION="$REGION",_REPO_REGION="$REPO_REGION",_API_KEY="$API_KEY",_INSTANCE_NAME_NUM="$ID" &
done

wait
