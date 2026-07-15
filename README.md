## Multi-Agent Web Research & Summarization Pipeline

## Overview

- Developed an **autonomous multi-agent web research and summarization system** that performs end-to-end research on user-specified topics.
- Implements a collaborative **Planner → Searcher → Synthesizer → Critic** workflow coordinated by a **Supervisor** for intelligent task orchestration.
- Uses a **Message Bus** (Redis Streams or an in-memory implementation) to enable asynchronous communication between independent agents.
- Generates **structured, citation-backed research reports** by retrieving, synthesizing, and validating information from multiple sources.
- Supports **iterative feedback loops**, allowing the Critic agent to request additional research until the desired quality threshold is achieved.
- Designed with a **modular and scalable architecture**, enabling agents to run either in-process or as independent distributed services using Docker and Redis.


## High-Level Architecture
                  
<img width="1440" height="700" alt="image" src="https://github.com/user-attachments/assets/c6a2ea03-f78c-45bd-946e-dfac0ed17573" />

  

## Folder Structure
```
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
```

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

## Run Pipeline

**Option 1. Run locally without docker**

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

**Option 2.  Run with Docker** 

**linux/mac**

GNU Make is installed:
```
make run
```

**Windows PowerShell**

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
