.PHONY: keys token run test lint fmt chat check widget-install widget-dev widget-test widget-build admin-install admin-dev admin-test admin-build admin-types start stop restart status logs

PERSONA ?= sales_rep@globex
TTL ?= 3600

keys:          ## generate the local RSA signing keypair into .local/keys/
	uv run python -m tools.keys

token:         ## mint a JWT: make token PERSONA=sales_manager@acme, or ADMIN=editor@ops
	@uv run python -m tools.mint_token $(if $(ADMIN),--admin $(ADMIN),--persona $(PERSONA)) --ttl $(TTL)

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

check: lint test widget-test admin-test  ## everything CI would run

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
