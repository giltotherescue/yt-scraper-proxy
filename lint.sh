set -euxo pipefail

poetry run pre-commit install
poetry run pre-commit run --all-files --show-diff-on-failure
