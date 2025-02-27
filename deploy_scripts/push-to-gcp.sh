#!/bin/bash

# Load variables from .env file
set -o allexport
source ./.env set
set +o allexport

# Generate UNIQUE_PREFIX on the fly
UNIQUE_PREFIX=$(date "+%Y-%m-%d-%H%M%S")

# Run the gcloud builds submit command with substitutions
gcloud builds submit --config deploy_scripts/push_container_to_gcp.yaml \
  --project "$PROJECT_ID" \
  --substitutions \
    _SUB_NAME_PREFIX="$SUB_NAME_PREFIX",_UNIQUE_PREFIX="$UNIQUE_PREFIX",_ARTIFACT_REPO="$ARTIFACT_REPO",_REPO_REGION="$REPO_REGION"
