.PHONY: run build up down test verify clean distributed logs

COMPOSE := docker compose

## Single command: build image, start Redis, run the full pipeline against
## sample_topics.json, verify the outputs, then tear infrastructure down.
run:
	$(COMPOSE) build
	$(COMPOSE) up -d redis
	$(COMPOSE) run --rm app
	./verify.sh
	$(COMPOSE) down

## Same, but every agent runs as its own container over Redis Streams.
distributed:
	$(COMPOSE) build
	$(COMPOSE) --profile distributed up -d redis agent-planner agent-searcher agent-synthesizer agent-critic
	sleep 2
	$(COMPOSE) run --rm -e BUS_BACKEND=redis app --topics-file sample_topics.json --output-dir /app/outputs --bus redis
	./verify.sh
	$(COMPOSE) --profile distributed down

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d redis

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f

## Local (non-docker) test run - useful during development.
test:
	pip install -r requirements.txt --quiet
	pytest -q

verify:
	./verify.sh

clean:
	rm -rf outputs/*.json outputs/*.trace.json data/mock_dataset.json __pycache__ .pytest_cache
