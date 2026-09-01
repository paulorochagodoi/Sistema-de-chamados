# Atalhos de operação do stack ITSM.
# Uso: make <alvo>   (make help lista tudo)

COMPOSE_FILE := deploy/compose/docker-compose.yml
TLS_FILE     := deploy/compose/docker-compose.tls.yml
ENV_FILE     := .env
COMPOSE      := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
BRIDGE_DIR   := services/itsm-bridge
ALL_PROFILES := --profile core --profile rmm --profile omnichannel \
                --profile automation --profile bi --profile observability

.DEFAULT_GOAL := help
.PHONY: help env configure install up up-rmm up-omnichannel up-automation \
        up-bi up-observability up-all up-tls down clean ps logs restart smoke \
        backup test lint validate build-bridge build-portal reset

help: ## Lista os alvos disponíveis
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

env: ## Cria o .env a partir do exemplo e gera os segredos
	@test -f $(ENV_FILE) || cp .env.example $(ENV_FILE)
	@./scripts/gen-secrets.sh

configure: ## Ajusta o .env (domínio, e-mail, fuso, perfis, tokens do GLPI)
	@./scripts/configure.sh

install: ## Instala tudo no Ubuntu (Docker, firewall, systemd) e sobe a stack
	@./scripts/install-ubuntu.sh

up: env ## Sobe o núcleo (Fase 1)
	$(COMPOSE) --profile core up -d

up-rmm: env ## Sobe núcleo + RMM/acesso remoto (Fase 2)
	$(COMPOSE) --profile core --profile rmm up -d

up-omnichannel: env ## Sobe núcleo + Chatwoot (Fase 3)
	$(COMPOSE) --profile core --profile omnichannel up -d

up-automation: env ## Sobe núcleo + n8n e RabbitMQ (Fase 3)
	$(COMPOSE) --profile core --profile automation up -d

up-bi: env ## Sobe núcleo + Metabase
	$(COMPOSE) --profile core --profile bi up -d

up-observability: env ## Sobe núcleo + Prometheus/Grafana/Loki (Fase 5)
	$(COMPOSE) --profile core --profile observability up -d

up-all: env ## Sobe todos os perfis
	$(COMPOSE) $(ALL_PROFILES) up -d

up-tls: env ## Sobe o núcleo com certificados Let's Encrypt (produção)
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) -f $(TLS_FILE) \
	  --profile core up -d

down: ## Para os containers, preservando os volumes
	$(COMPOSE) $(ALL_PROFILES) down

clean: ## Remove containers, redes E volumes (DESTRUTIVO)
	$(COMPOSE) $(ALL_PROFILES) down -v

reset: ## Apaga instalação: containers, volumes, .env (DESTRUTIVO; --help p/ opções)
	@./scripts/reset.sh

ps: ## Estado dos containers
	$(COMPOSE) $(ALL_PROFILES) ps

logs: ## Logs de um serviço: make logs SERVICE=glpi
	$(COMPOSE) logs -f --tail=200 $(SERVICE)

restart: ## Reinicia um serviço: make restart SERVICE=itsm-bridge
	$(COMPOSE) restart $(SERVICE)

build-bridge: ## Recompila a imagem do itsm-bridge
	$(COMPOSE) build itsm-bridge

build-portal: ## Recompila a imagem do portal (painel unificado)
	$(COMPOSE) build portal

smoke: ## Verificação pós-deploy
	@./scripts/smoke-test.sh

backup: ## Backup de bancos, volumes e configuração
	@./scripts/backup.sh

test: ## Testes do itsm-bridge
	cd $(BRIDGE_DIR) && python -m pytest

lint: ## Lint do itsm-bridge
	cd $(BRIDGE_DIR) && python -m ruff check .

validate: ## Valida a sintaxe do Compose (todos os perfis) e do overlay TLS
	docker compose --env-file .env.example -f $(COMPOSE_FILE) $(ALL_PROFILES) config -q
	docker compose --env-file .env.example -f $(COMPOSE_FILE) -f $(TLS_FILE) \
	  --profile core config -q
	@echo "Compose OK"
