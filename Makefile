.PHONY: up down db-reset db-shell migrate ingest index-list promote rollback embed-smoke rerank-smoke eval eval-baseline keys token spec spec-check docs-check docs-gen docs-sample evals-targets evals-check evals-gen evals-sample llm-smoke run test lint fmt chat check widget-install widget-dev widget-test widget-build admin-install admin-dev admin-test admin-build admin-types start stop restart status logs

PERSONA ?= sales_rep@globex
TTL ?= 3600

# --- local infrastructure: Postgres + pgvector and Phoenix on Colima ------------

up:            ## start Colima if needed, Postgres + Phoenix, wait for health, migrate
	@scripts/infra.sh up

down:          ## stop the containers (data kept; `colima stop` frees the VM's memory)
	@scripts/infra.sh down

db-reset:      ## delete all local Postgres and Phoenix data (asks first)
	@scripts/infra.sh reset

db-shell:      ## psql into the dev database
	@scripts/infra.sh shell

migrate:       ## apply database migrations (alembic upgrade head)
	uv run alembic upgrade head

# --- index versions (S2.1.3); needs `make up` -----------------------------------

ingest:        ## validate, chunk, embed (cache first) data/docs into a new index version and make it live (ungated until S2.4.1)
	uv run python -m tools.ingest build --promote

index-list:    ## list index versions and which one is live
	@uv run python -m tools.ingest list

promote:       ## make a complete index version live: make promote V=3
	@test -n "$(V)" || { echo "usage: make promote V=<index version>"; exit 2; }
	uv run python -m tools.ingest promote $(V)

rollback:      ## undo the last repoint of the live index
	uv run python -m tools.ingest rollback

embed-smoke:   ## load bge-m3 (downloads ~2.3 GB the first time) and sanity-check it
	uv run python -m tools.ingest embed-smoke

eval:          ## retrieval evals + permission suite on the live index (or V=n); fails on any leak; saved to evals/reports/retrieval/
	uv run python -m tools.eval_retrieval $(if $(V),--version $(V))

eval-baseline: ## make eval, and also write the committed baseline evals/baselines/retrieval.{md,json}
	uv run python -m tools.eval_retrieval --baseline $(if $(V),--version $(V))

rerank-smoke:  ## load bge-reranker-v2-m3 (downloads ~2.3 GB the first time), check it, time 20 candidates
	uv run python -m tools.rerank_smoke

keys:          ## generate the local RSA signing keypair into .local/keys/
	uv run python -m tools.keys

token:         ## mint a JWT: make token PERSONA=sales_manager@acme, or ADMIN=editor@ops
	@uv run python -m tools.mint_token $(if $(ADMIN),--admin $(ADMIN),--persona $(PERSONA)) --ttl $(TTL)

spec:          ## regenerate data/personas.yaml and data/module_catalogue.yaml from data/spec/crm_spec.yaml
	uv run python -m tools.spec derive

spec-check:    ## validate the CRM spec and fail if the generated files are stale
	uv run python -m tools.spec check

docs-check:    ## validate the doc plan and the synthetic corpus (every planned doc must exist)
	uv run python -m tools.docgen check --require-all

DOCS ?=

docs-gen:      ## write missing synthetic docs with the LLM (costs money): make docs-gen DOCS="id id"
	uv run python -m tools.docgen generate $(if $(DOCS),--only $(DOCS))

docs-sample:   ## list the docs to hand-review (flagged ones first)
	@uv run python -m tools.docgen sample

evals-targets: ## rebuild evals/synthetic/targets.yaml from the seeds and the doc plan (no LLM)
	uv run python -m tools.evalgen targets

evals-check:   ## validate eval targets and every golden question (labels resolve, outcomes re-derived)
	uv run python -m tools.evalgen check

TIDS ?=

evals-gen:     ## write missing eval questions with the LLM (costs money): make evals-gen TIDS="t-001 t-002"
	uv run python -m tools.evalgen generate $(if $(TIDS),--only $(TIDS))

evals-sample:  ## list eval questions to hand-review, with labels and expected outcomes
	@uv run python -m tools.evalgen sample

ROLE ?=

llm-smoke:     ## one tiny live call per model role (needs OPENROUTER_API_KEY): make llm-smoke ROLE=docgen
	uv run python -m tools.llm_smoke $(if $(ROLE),--role $(ROLE))

WIDGET_ORIGIN ?= http://localhost:5173
ADMIN_ORIGIN ?= http://localhost:5174

run:           ## run the API locally (CORS open to the widget and admin dev servers only)
	CHATBOT_CORS_ORIGINS='["$(WIDGET_ORIGIN)","$(ADMIN_ORIGIN)"]' \
	  uv run uvicorn --factory chatbot.api.app:create_app --reload --reload-dir src --port 8000

test:          ## unit tests
	uv run pytest

lint:          ## ruff + mypy (strict)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

fmt:
	uv run ruff check --fix .
	uv run ruff format .

Q ?= how do I email contacts when a deal changes stage

chat:          ## stream a mock answer: make chat PERSONA=sales_rep@globex Q="..."
	@curl -sN -X POST localhost:8000/chat \
	  -H "Authorization: Bearer $$(uv run python -m tools.mint_token --persona $(PERSONA))" \
	  -H "Content-Type: application/json" \
	  -d "$$(uv run python -c 'import json, sys; print(json.dumps({"message": sys.argv[1]}))' "$(Q)")"

widget-install: ## install widget dependencies (exact versions from package-lock.json)
	cd widget && npm ci

widget-dev:    ## widget + fake-CRM harness on http://localhost:5173 (needs `make run`)
	cd widget && npm run dev

widget-test:   ## widget unit tests + typecheck
	cd widget && npm test && npm run typecheck

widget-build:  ## build widget/dist/crm-help-bot.js
	cd widget && npm run build

admin-install: ## install admin app dependencies (exact versions from package-lock.json)
	cd admin && npm ci

admin-dev:     ## admin app on http://localhost:5174 (needs `make run`)
	cd admin && npm run dev

admin-test:    ## admin app unit tests + typecheck
	cd admin && npm test && npm run typecheck

admin-build:   ## build admin/dist
	cd admin && npm run build

admin-types:   ## regenerate admin/src/api/schema.d.ts from the API's OpenAPI schema
	uv run python -m tools.dump_openapi admin/openapi.json
	cd admin && npm run types

check: lint spec-check docs-check evals-check test widget-test admin-test  ## everything CI would run

# --- all dev servers at once (API :8000, widget :5173, admin :5174) ---------------
# Pick a subset with S, e.g. `make restart S=api`.
S ?=

start:         ## start the API, widget and admin app in the background
	@scripts/dev.sh start $(S)

stop:          ## stop them (also stops a `make run` etc. of this repo started elsewhere)
	@scripts/dev.sh stop $(S)

restart:       ## stop, then start
	@scripts/dev.sh restart $(S)

status:        ## what's running, and where
	@scripts/dev.sh status

logs:          ## follow server logs (Ctrl-C to quit)
	@scripts/dev.sh logs $(S)
