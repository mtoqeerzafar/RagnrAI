# RagnrAI New Environment Setup Guide

This guide details everything you need to install and configure to run RagnrAI natively on a new Windows company laptop. 

> [!WARNING]
> Because this is a heavy AI application running local embedding models and document parsers, **Microsoft Visual C++ Build Tools** are strictly required on Windows to compile Python C-extensions.

---

## 1. System Requirements & Prerequisites

Before touching the codebase, you must install the following core software on your new machine:

### A. Python & Build Tools
1. **Python 3.12**: Download and install [Python 3.12](https://www.python.org/downloads/). Ensure you check the box that says **"Add Python to PATH"** during installation.
2. **Microsoft Visual C++ Build Tools**: 
   - Download the [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).
   - During installation, check the box for **"Desktop development with C++"**. This installs the necessary MSVC compiler required to build Python packages like `fastembed` and `docling` natively on Windows.

### B. Containerization & Database Engines
1. **Docker Desktop**: Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
   - Ensure you are using the **WSL 2 backend** (Windows Subsystem for Linux) in the Docker settings for optimal performance.

### C. Node.js (Frontend)
1. **Node.js (v20+)**: Download and install [Node.js](https://nodejs.org/). This will also install `npm`.

### D. IDE & Version Control
1. **Git**: Download and install [Git for Windows](https://git-scm.com/download/win).
2. **Antigravity IDE**: Install your Antigravity (Gemini) IDE setup.

---

## 2. Project Initialization

Once the prerequisites are installed, open your terminal (or Antigravity IDE) and follow these steps to bootstrap the project:

### Step 1: Start Infrastructure (Docker)
In the root directory of `RagnrAI`, start the 4 core databases (PostgreSQL, Redis, MinIO, and Qdrant) in detached mode:
```bash
docker-compose up -d
```
> [!NOTE]
> This will pull the images and start the services. You can verify they are running by opening Docker Desktop.

### Step 2: Python Environment & Dependencies
Create a clean Python 3.12 virtual environment and install the heavy ML dependencies:
```bash
# Create virtual environment
python -m venv venv312

# Activate it (Windows PowerShell)
.\venv312\Scripts\Activate.ps1

# Upgrade pip (Important for compiling C-extensions)
python -m pip install --upgrade pip setuptools wheel

# Install all backend requirements
pip install -r requirements.txt
```

### Step 3: Database Migrations
Initialize the PostgreSQL tables:
```bash
# Apply alembic migrations
alembic upgrade head
```
*(If Alembic is not configured yet, you may need to rely on SQLAlchemy `Base.metadata.create_all(bind=engine)` during FastAPI startup)*.

### Step 4: Environment Variables
Create a `.env` file in the root directory (copy from `.env.example` if it exists). Ensure you have your keys set up:
```env
# Required for LLM Generation
GROQ_API_KEY=your_groq_api_key

# Optional: For LangGraph Visualization
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=ragnrai-production

# Qdrant & MinIO (Matches Docker Compose)
QDRANT_URL=http://localhost:6333
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=password123
```

### Step 5: Frontend Dependencies
Navigate to the frontend folder and install the Node packages:
```bash
cd frontend
npm install
cd ..
```

---

## 3. Running the Application

To run the full stack, you need to open **three separate terminal windows** (ensure your Python virtual environment is activated in the first two).

**Terminal 1: The FastAPI Backend**
```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2: The Celery Background Worker**
> [!IMPORTANT]
> Because you are on Windows, Celery does not support the default `fork` pool. You **must** run it using `--pool=solo`.
```bash
python -m celery -A workers.celery_app worker --loglevel=info --pool=solo
```

**Terminal 3: The Next.js/Vite Frontend**
```bash
cd frontend
npm run dev
```

Your app is now fully operational! You can access the UI at `http://localhost:3000` (or whichever port the frontend framework outputs) and the API docs at `http://localhost:8000/docs`.
