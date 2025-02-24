#!/bin/bash

# Load variables from .env file
set -o allexport
source ./.env set
set +o allexport

# Generate UNIQUE_PREFIX on the fly
UNIQUE_PREFIX=$(date "+%Y-%m-%d-%H%M%S")

#cd ..
# Run the gcloud builds submit command with substitutions
gcloud builds submit --config deploy_scripts/deploy_cloudbuild_cr.yaml \
  --project "$PROJECT_ID" \
  --substitutions \
    _PROJECT_ID="$PROJECT_ID",_PORT="$SERVER_PORT",_SUB_NAME_PREFIX="$SUB_NAME_PREFIX",_UNIQUE_PREFIX="$UNIQUE_PREFIX",_ARTIFACT_REPO="$ARTIFACT_REPO",_REGION="$REGION",_API_KEY="$API_KEY"
