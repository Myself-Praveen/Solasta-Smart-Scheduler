<h1 align="center">
  🧠 Solasta — Smart Study Schedule Agent
</h1>

<p align="center">
  <strong>An autonomous AI agent that thinks, plans, and delivers personalized study schedules</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Track-AI%20Agents%20That%20Think%2C%20Plan%20%26%20Deliver-6c63ff?style=for-the-badge" alt="Hackathon Track" />
  <img src="https://img.shields.io/badge/Bonus-+5%20Points-34d399?style=for-the-badge" alt="Bonus Track" />
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js&logoColor=white" alt="Next.js" />
</p>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Setup & Installation](#-setup--installation)
- [Running the Application](#-running-the-application)
- [How It Works](#-how-it-works)
- [API Endpoints](#-api-endpoints)
- [Screenshots](#-screenshots)
- [Hackathon Requirements](#-hackathon-requirements-compliance)

---

## 🌟 Overview

**Solasta** is an autonomous AI-powered study schedule agent built for the **Solasta 2026 Hackathon** under the "Bridge Intent and Action: Build AI Agents That Think, Plan, and Deliver" track.

Unlike traditional chatbots that simply respond, Solasta **autonomously decomposes** a natural language study goal (e.g., *"Plan my GATE exam schedule for 3 months"*) into a multi-step execution plan, **executes each step using specialized tools**, **evaluates results**, and **replans on failure** — all streamed in real-time to a premium dark-themed dashboard.

### 🚀 Live Demos
- **Frontend (Vercel):** [https://solasta-smart-scheduler.vercel.app](https://solasta-smart-scheduler.vercel.app)
- **Backend (Render):** [https://solasta-smart-scheduler.onrender.com/health](https://solasta-smart-scheduler.onrender.com/health)

---

## 🏗️ Architecture

Solasta implements a **4-Agent Cognitive Architecture** inspired by the Plan-Execute-Evaluate loop:

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                         │
│         (Coordinates the entire pipeline)               │
├────────────┬──────────────┬──────────────┬──────────────┤
│  🧠 PLANNER │  ⚡ EXECUTOR  │  🔍 EVALUATOR │ 🔄 REPLANNER│
│            │              │              │              │
│ Decomposes │ Runs tools   │ Validates    │ Adapts plan  │
│ goal into  │ for each     │ each step's  │ on failure   │
│ DAG plan   │ step         │ output       │ or low score │
└────────────┴──────────────┴──────────────┴──────────────┘
         │                                    │
         ▼                                    ▼
  ┌─────────────┐                    ┌─────────────────┐
  │  Tool Suite  │                    │  SQLite (Local)  │
  │ 9 Registered │                    │  Persistent DB   │
  └─────────────┘                    └─────────────────┘
```

### Agent Descriptions

| Agent | Role | Description |
|-------|------|-------------|
| **Planner** | 🧠 Think | Receives a natural language goal and decomposes it into a directed acyclic graph (DAG) of 6-7 executable steps with dependencies, priorities, and expected outcomes |
| **Executor** | ⚡ Act | Takes each step and invokes the appropriate registered tool (e.g., `analyze_syllabus`, `create_schedule`, `fetch_study_resources`) |
| **Evaluator** | 🔍 Verify | Validates the output of each step, assigning a confidence score and determining pass/fail |
| **Replanner** | 🔄 Adapt | When a step fails or scores below threshold, dynamically generates a revised plan to recover |

---

## ✨ Key Features

### 🤖 Autonomous Intelligence
- **Natural Language Goal Processing** — Input any study goal in plain English
- **Automatic Plan Decomposition** — Goals are broken into 6-7 step DAG plans
- **Self-Correcting Execution** — Failed steps trigger automatic replanning
- **Experience-Aware Planning** — Recalls past successful plans for similar goals

### 🛠️ Tool Suite (9 Registered Tools)
| Tool | Description |
|------|-------------|
| `analyze_syllabus` | Parses goals to extract exam-specific subjects & topics |
| `assess_difficulty` | Evaluates topic difficulty relative to student level |
| `generate_study_tips` | Creates personalized study strategies per topic |
| `fetch_study_resources` | **Live Wikipedia API** — Fetches real-world summaries & URLs |
| `create_schedule` | Generates detailed week-by-week study timetables |
| `allocate_time_blocks` | Distributes study hours using Pomodoro technique |
| `detect_conflicts` | Checks for scheduling conflicts in the final plan |
| `save_to_database` | Persists the validated schedule to SQLite |
| `validate_schedule` | Final validation and quality check |

### 🌐 Live API Integration
- **Wikipedia REST API** — Real-time resource fetching with proper `User-Agent` compliance
- Live HTTP requests demonstrate the "Act" requirement of the hackathon

### 📅 Actionable Output
- **📄 PDF Export** — Download a beautifully formatted study schedule PDF
- **📅 iCalendar Export** — Generate `.ics` files importable into Google Calendar, Outlook, Apple Calendar

### 🧠 Transparent Intelligence ("View Brain")
- Every step exposes its **Chain-of-Thought** reasoning
- View expected outcomes, priorities, dependencies, and tools used
- Click "🧠 View Brain" on any step to inspect the agent's reasoning

### 💾 Full Persistence
- All goals, plans, steps, and agent logs stored in **local SQLite** via `aiosqlite`
- Past sessions accessible from the sidebar
- Complete **Agent Execution Logs** viewable via modal

### 🎨 Premium UI
- Dark glassmorphism theme with gradient accents
- Real-time SSE streaming with animated chat bubbles
- Step timeline with color-coded status indicators
- Responsive split-screen layout (Chat + Execution Plan)

---

## 🛠️ Tech Stack

### Backend
| Technology | Purpose |
|-----------|---------|
| **Python 3.11+** | Core language |
| **FastAPI** | Async REST API framework |
| **LangChain** | LLM orchestration & tool management |
| **Ollama** | Local LLM inference (primary) |
| **Google Gemini** | Cloud LLM fallback |
| **OpenAI** | Tertiary LLM fallback |
| **SQLite + aiosqlite** | Local persistent database |
| **SSE (Server-Sent Events)** | Real-time streaming to frontend |
| **httpx** | Async HTTP client for live API calls |

### Frontend
| Technology | Purpose |
|-----------|---------|
| **Next.js 16** | React framework |
| **React 19** | UI library |
| **TypeScript** | Type safety |
| **jsPDF + html2canvas** | PDF generation |
| **Vanilla CSS** | Custom glassmorphism design system |

---

## 📁 Project Structure

```
SOLASTA SMART SCHEDULER/
├── app/                          # Backend (Python/FastAPI)
│   ├── main.py                   # FastAPI entry point, SSE streaming, CORS
│   ├── api/                      # REST API routes
│   │   └── routes.py             # Goal CRUD, plan retrieval, log endpoints
│   ├── cognitive/                # 4-Agent Cognitive Architecture
│   │   ├── agents/
│   │   │   ├── planner.py        # 🧠 PlannerAgent — goal decomposition
│   │   │   ├── executor.py       # ⚡ ExecutorAgent — tool invocation
│   │   │   ├── evaluator.py      # 🔍 EvaluatorAgent — result validation
│   │   │   └── replanner.py      # 🔄 ReplannerAgent — adaptive replanning
│   │   ├── llm/
│   │   │   └── gateway.py        # LLM provider gateway (Ollama/Gemini/OpenAI)
│   │   └── memory/
│   │       └── context.py        # Shared execution context & memory
│   ├── core/
│   │   └── models.py             # Pydantic models (Goal, Plan, Step, etc.)
│   ├── db/
│   │   └── database.py           # SQLite database setup & session management
│   ├── orchestrator/
│   │   └── orchestrator.py       # Main pipeline orchestrator
│   ├── schemas/
│   │   └── api_schemas.py        # API request/response schemas
│   └── tools/
│       └── study_tools.py        # 9 registered study tools + Wikipedia API
│
├── frontend/                     # Frontend (Next.js/React)
│   ├── src/
│   │   └── app/
│   │       ├── page.tsx          # Main dashboard (Chat + Execution Plan)
│   │       ├── api.ts            # API client (fetch goals, plans, logs)
│   │       ├── globals.css       # Design system (glassmorphism, animations)
│   │       └── layout.tsx        # Root layout with metadata
│   ├── package.json
│   └── tsconfig.json
│
├── .env.example                  # Environment variable template
├── .gitignore
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Docker configuration
├── docker-compose.yml            # Docker Compose setup
├── supabase_schema.sql           # Database schema (SQL)
└── README.md                     # This file
```

---

## 🚀 Setup & Installation

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** and **npm**
- **Ollama** (for local LLM) — [Install Ollama](https://ollama.ai)
- A **Google Gemini API key** (optional fallback)

### 1. Clone the Repository

```bash
git clone https://github.com/Myself-Praveen/Solasta-Smart-Scheduler.git
cd Solasta-Smart-Scheduler
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv venv

# Activate it
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your API keys
# REQUIRED: Set at least one LLM provider
# The app uses Ollama (local) as primary, Gemini as fallback
```

### 4. Ollama Setup (Local LLM)

```bash
# Pull the default model
ollama pull llama3

# Verify it's running
ollama list
```

### 5. Frontend Setup

```bash
cd frontend
npm install
cd ..
```

---

## ▶️ Running the Application

### Start Both Servers

**Terminal 1 — Backend (FastAPI):**
```bash
.\venv\Scripts\activate          # Windows
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Frontend (Next.js):**
```bash
cd frontend
npm run dev
```

### Access the Application
- **Frontend Dashboard**: [http://localhost:3000](http://localhost:3000)
- **Backend API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🔄 How It Works

```
User Input                    "Plan my GATE exam schedule for 3 months"
    │
    ▼
┌──────────┐
│ PLANNER  │  ──▶  Decomposes into 7-step DAG plan
└──────────┘       (with dependencies, tools, priorities)
    │
    ▼
┌──────────┐       Step 1: analyze_syllabus
│ EXECUTOR │  ──▶  Step 2: assess_difficulty
└──────────┘       Step 3: generate_study_tips
    │              Step 4: fetch_study_resources (Live Wikipedia API)
    │              Step 5: create_schedule
    │              Step 6: allocate_time_blocks
    │              Step 7: validate_schedule & save_to_database
    ▼
┌───────────┐
│ EVALUATOR │  ──▶  Validates each step's output (confidence scoring)
└───────────┘
    │
    ▼ (if failed)
┌───────────┐
│ REPLANNER │  ──▶  Generates revised plan & retries
└───────────┘
    │
    ▼
📄 PDF + 📅 .ics    Actionable, downloadable outputs
```

### Real-Time Streaming
The entire execution is streamed to the frontend via **Server-Sent Events (SSE)**:
- `plan_created` — Plan with all steps received
- `step_started` — Step execution begins
- `step_update` — Step status changes (in-progress → evaluating → completed)
- `goal_completed` — All steps finished successfully
- `goal_failed` — Execution failed after retries

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/goal` | Submit a new study goal (returns SSE stream) |
| `GET` | `/api/goals` | List all past goals |
| `GET` | `/api/goals/{id}` | Get a specific goal |
| `GET` | `/api/goals/{id}/plan` | Get the execution plan for a goal |
| `GET` | `/api/goals/{id}/logs` | Get agent execution logs |
| `GET` | `/api/logs/all` | Get all system logs |
| `GET` | `/health` | Health check |

---

## 📸 Screenshots

### 🏠 Landing Page
Premium dark-themed chat interface with suggested study goals.

### ⚡ Real-Time Execution
Split-screen layout showing chat messages on the left and the execution plan timeline on the right, with live step-by-step updates.

### 🧠 Agent Brain View
Expandable "View Brain" panel for each step showing Chain-of-Thought reasoning, expected outcomes, priorities, dependencies, and tools used.

### 📄 Export Options
"Download PDF" and "Add to Calendar (.ics)" buttons appear upon completion, providing actionable deliverables.

---

## ✅ Hackathon Requirements Compliance

| Requirement | Status | Implementation |
|------------|--------|----------------|
| **Think** — Understand natural language intent | ✅ | PlannerAgent decomposes goals using LLM reasoning |
| **Plan** — Create a multi-step execution plan | ✅ | DAG-based plan with 6-7 steps, dependencies, priorities |
| **Act** — Execute steps autonomously with tools | ✅ | 9 registered tools including live Wikipedia API calls |
| **Verify** — Validate outputs | ✅ | EvaluatorAgent with confidence scoring |
| **Adapt** — Replan on failure | ✅ | ReplannerAgent generates revised plans dynamically |
| **Persist** — Store data locally | ✅ | SQLite via aiosqlite for goals, plans, steps, logs |
| **Actionable Results** | ✅ | PDF download + iCalendar (.ics) export |
| **Real-Time UI** | ✅ | SSE streaming with live chat + execution plan |
| **Transparent Intelligence** | ✅ | "View Brain" exposes agent thought process per step |
| **ASI:One Chat Protocol** | ✅ | Natural language chat interface |
| **Bonus Track (+5)** | ✅ | Selected "AI Agents That Think, Plan, and Deliver" |

---

## 🏆 Team

Built with ❤️ for **Solasta 2026 Hackathon**

---

## 📜 License

This project is built for the Solasta 2026 Hackathon evaluation.
