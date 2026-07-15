## Multi-Agent Web Research & Summarization Pipeline
Overview

This project is an autonomous multi-agent research system that performs end-to-end web research on a given topic. A team of AI agents collaborates to plan the research, gather relevant information, generate a structured report, and validate its quality before producing the final output.

The workflow follows a Planner → Searcher → Synthesizer → Critic pipeline, coordinated by a Supervisor. Agents communicate exclusively through a Message Bus (Redis Streams or an in-memory implementation), enabling a scalable and loosely coupled architecture.


## High-Level Architecture
                    ┌──────────────┐
   Topic ──────────▶│  Supervisor  │
                    └──────┬───────┘
                           │
                           ▼
                ┌───────────────────────┐
                │      Message Bus      │
                │ Redis / In-Memory Bus │
                └───────────────────────┘
                   │       │       │
                   ▼       ▼       ▼
              Planner → Searcher → Synthesizer → Critic
                                    ▲               │
                                    └────Feedback───┘
                                      (max 2 retries)

## Folder Structure

multi_agent_research/
│
├── src/
│   ├── agents/             
│   ├── orchestrator/        # workflow management
│   ├── data/               
│   ├── utils/               
│   ├── message_bus.py       # Redis message bus
│   ├── schemas.py           # Input & output schemas
│   ├── config.py
│   └── main.py
│
├── outputs/                 # generated reports
├── tests/                   # Unit & integration tests
├── data/                    # mock search dataset
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── verify.sh
├── sample_topics.json
├── requirements.txt
└── README.md


## Setup

## Clone Repository 
```
git clone <repo_url>
cd multi_agent_research
```

## Install Dependencies
```
pip install -r requirements.txt 
pip install pytest
```

## Running the Project

Option 1. Run Locally 

Run the pipeline without docker
```
python -m src.main --topics-file sample_topics.json --output-dir outputs
```

Run a single topic:
```
python -m src.main \
    --topic "Impact of AI on labor markets" \
    --depth deep \
    --output-dir outputs
```

Option 2.  Run with Docker 

## Linux/macOS/WSL

GNU Make is installed:
```
make run
```

## Windows PowerShell

Windows does not include GNU Make by default. Run the equivalent commands manually:
```
docker compose build
docker compose up -d redis
docker compose run --rm app
docker compose down
```


## Running Tests
```
pytest
 ```
or
```
make test
```

## Mock Search Backend

It uses a synthetic search dataset (~10,000 documents) spanning multiple domains such as AI, healthcare, climate, and energy. Documents are ranked using a simple keyword-overlap algorithm, enabling search, ranking, and citation functionality without requiring internet access or external search APIs.

## Current Limitations
- Uses a synthetic search dataset instead of live web search.
- Search ranking is based on keyword overlap rather than    semantic retrieval.
- Reports are currently exported only in JSON format; PDF generation is planned for future enhancement.
