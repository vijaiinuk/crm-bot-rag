.PHONY: keys token run test lint fmt

PERSONA ?= sales_rep@globex
TTL ?= 3600

keys:          ## generate the local RSA signing keypair into .local/keys/
	uv run python -m tools.keys

token:         ## mint a persona JWT: make token PERSONA=sales_manager@acme
	@uv run python -m tools.mint_token --persona $(PERSONA) --ttl $(TTL)

run:           ## run the API locally
	uv run uvicorn --factory chatbot.api.app:create_app --reload --port 8000

test:          ## unit tests
	uv run pytest

lint:          ## ruff + mypy (strict)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

fmt:
	uv run ruff check --fix .
	uv run ruff format .
