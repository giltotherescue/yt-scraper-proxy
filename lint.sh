set -euxo pipefail

pre-commit install
pre-commit run --all-files --show-diff-on-failure
