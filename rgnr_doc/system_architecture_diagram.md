# RagnrAI Detailed System Architecture

This document contains a minute-detail architectural diagram of the `RagnrAI` production system, tracing the exact data flow of document ingestion (via MinIO) and user query execution (via SSE and LangGraph) starting explicitly from the End User interacting with the Next.js frontend.

## Architecture Diagram

```mermaid
flowchart TD
    %% Define Styles
    classDef user fill:#3498db,stroke:#333,stroke-width:2px,color:#fff,shape:circle
    classDef client fill:#2a2a2a,stroke:#333,stroke-width:2px,color:#fff
    classDef api fill:#0f4c81,stroke:#333,stroke-width:2px,color:#fff
    classDef worker fill:#8e44ad,stroke:#333,stroke-width:2px,color:#fff
    classDef db fill:#27ae60,stroke:#333,stroke-width:2px,color:#fff
    classDef cache fill:#e67e22,stroke:#333,stroke-width:2px,color:#fff
    classDef agent fill:#c0392b,stroke:#333,stroke-width:2px,color:#fff
    classDef logic fill:#f39c12,stroke:#333,stroke-width:1px,color:#fff
    classDef ext fill:#7f8c8d,stroke:#333,stroke-width:2px,color:#fff,stroke-dasharray: 5 5

    %% 1. USER & CLIENT LAYER
    subgraph ClientLayer ["Client & Edge"]
        EndUser(("End User")):::user
        UI["Next.js Web Client"]:::client
    end

    %% 2. MINIO / S3 STORAGE
    subgraph StorageLayer ["Object Storage"]
        MinIO[("MinIO (S3 Compatible Storage)")]:::db
    end

    %% 3. API & MEMORY LAYER
    subgraph APILayer ["FastAPI Backend (api/main.py)"]
        API_Upload["/api/upload-url & /api/process"]:::api
        API_Query["/api/query/stream (SSE)"]:::api
        MemoryManager["Memory Manager (Sliding Window)"]:::logic
        MemorySummarizer["LLM: Groq 8B Summarizer"]:::agent
    end

    %% 4. INGESTION PIPELINE (ASYNC)
    subgraph IngestionPipeline ["Background Ingestion Pipeline (Celery)"]
        CeleryWorker["Celery Worker Pool"]:::worker
        Docling["Docling DOM-based Parser"]:::logic
        FastEmbed["FastEmbed (CPU Local)"]:::logic
    end

    %% 5. ORCHESTRATION LAYER (LANGGRAPH DAG)
    subgraph LangGraph ["LangGraph Workflow Engine (agents/workflow.py)"]
        direction TB
        AgentWorkflow["AgentWorkflow State Machine"]:::logic
        
        %% Nodes
        NodePlan["3.1 WorkflowPlanner (8B JSON)"]:::agent
        NodeChat["3.2a Chat Responder"]:::agent
        NodeRewrite["3.2b QueryRewriter (8B Loop)"]:::agent
        NodeRetrieve["3.3 QdrantHybridRetriever"]:::logic
        NodeRerank["3.4 Diversity Reranker + FlashRank"]:::agent
        NodeRelevance["3.5 RelevanceChecker (8B JSON)"]:::agent
        NodeFallback["3.6a Fallback Rewriter"]:::agent
        NodeIrrelevant["3.6b Graceful Degradation"]:::logic
        NodeResearch["3.6c ResearchAgent (70B <thinking>)"]:::agent
        NodeVerify["3.7 VerificationAgent (8B Critic)"]:::agent
        NodeGuardrail["3.8 PIIGuardrail (Presidio)"]:::logic
        
        AgentWorkflow --> NodePlan
        NodePlan -->|"needs_retrieval=False"| NodeChat
        NodePlan -->|"needs_retrieval=True"| NodeRewrite
        NodeRewrite -->|"Standalone + Sub-queries"| NodeRetrieve
        NodeRetrieve --> NodeRerank
        NodeRerank --> NodeRelevance
        
        %% Relevance Routing
        NodeRelevance -->|"Sufficient = True"| NodeResearch
        NodeRelevance -->|"Sufficient = False & Attempts < 1"| NodeFallback
        NodeRelevance -->|"Sufficient = False & Attempts >= 1"| NodeIrrelevant
        
        NodeFallback -->|"Targeted sub-queries"| NodeRetrieve
        
        %% Generation & Verification Loop
        NodeResearch --> NodeVerify
        NodeVerify -->|"Supported = False & Revisions < 2"| NodeResearch
        NodeVerify -->|"Supported = True"| NodeGuardrail
        NodeIrrelevant --> NodeGuardrail
        NodeChat --> NodeGuardrail
    end

    %% 6. DATA STORES
    subgraph DataLayer ["State & Persistence"]
        PG_DB[("PostgreSQL")]:::db
        Redis[("Redis Exact Cache & Celery Broker")]:::cache
        Qdrant[("Qdrant Hybrid Vector DB")]:::db
        
        PG_Chat["ChatMessage Table"]:::db
        PG_Check["LangGraph PostgresSaver"]:::db
        Q_Docs["ragnr_documents (INT8 Quantized)"]:::db
        Q_Cache["semantic_cache"]:::db
    end

    %% EXTERNAL APIS
    GroqAPI(["Groq LLM API"]):::ext

    %% --- DETAILED CONNECTIONS ---

    %% Document Upload Flow
    EndUser -->|"1.0 Selects file to upload"| UI
    UI -->|"1.1 Request presigned URL"| API_Upload
    API_Upload -.->|"1.2 Returns presigned URL"| UI
    UI -->|"1.3 Uploads file directly"| MinIO
    UI -->|"1.4 Calls /api/process (s3_key)"| API_Upload
    API_Upload -->|"1.5 Offloads task"| Redis
    Redis -->|"1.6 Consumes task"| CeleryWorker
    CeleryWorker -->|"1.7 Downloads file"| MinIO
    CeleryWorker -->|"1.8 Extracts Structure"| Docling
    Docling -->|"1.9 Dense & Sparse Vectors"| FastEmbed
    FastEmbed -->|"1.10 Upserts points"| Q_Docs

    %% User Query Flow
    EndUser -->|"2.0 Types Question"| UI
    UI -->|"2.1 POST /api/query/stream"| API_Query
    API_Query -->|"2.2 Exact Match Check"| Redis
    API_Query -->|"2.3 Semantic Match Check"| Q_Cache
    API_Query -->|"2.4 Saves User Msg"| PG_Chat
    API_Query -->|"2.5 Fetches History"| MemoryManager
    MemoryManager -->|"2.6 Reads older msgs"| PG_Chat
    MemoryManager -->|"2.7 If > 4000 Tokens"| MemorySummarizer
    MemorySummarizer -->|"2.8 Compressed Context"| AgentWorkflow
    
    %% LangGraph Checkpointing & State
    AgentWorkflow -->|"Checkpoints state"| PG_Check
    
    %% Internal Graph Data Connections
    NodeRetrieve <-->|"gRPC Search (tenant_id)"| Q_Docs
    NodeRewrite <-->|"Checks prior queries"| Q_Cache
    
    %% LLM Inference Calls
    NodePlan -.->|"Inference"| GroqAPI
    NodeRewrite -.->|"Inference"| GroqAPI
    NodeRerank -.->|"Inference"| GroqAPI
    NodeRelevance -.->|"Inference"| GroqAPI
    NodeResearch -.->|"Inference"| GroqAPI
    NodeVerify -.->|"Inference"| GroqAPI
    MemorySummarizer -.->|"Inference"| GroqAPI
    
    %% Output Flow
    NodeGuardrail -->|"3.9 Strips PII"| API_Query
    API_Query -->|"4.0 Streams SSE (Hides <thinking>)"| UI
    UI -->|"4.1 Renders final answer"| EndUser
```

## Diagram Deep Dive: Key Execution Flows

### 1.0 Document Upload & Ingestion Flow
To avoid bottling up the FastAPI server with massive file payloads, the system implements a direct-to-storage architecture using **MinIO**:
- **[1.0 - 1.1] User Interaction & Auth**: The End User selects a PDF/document. The frontend requests a presigned URL.
- **[1.2 - 1.3] Presigned Upload**: The Next.js frontend uses the URL to upload the raw document directly to the MinIO object store.
- **[1.4 - 1.5] Task Queueing**: The frontend notifies the backend by calling `/api/process`. FastAPI pushes a background task onto the **Redis** Celery broker.
- **[1.6 - 1.8] Celery Processing**: An asynchronous Celery worker pulls the task, downloads the file from MinIO, and uses **Docling** to parse the DOM structure.
- **[1.9 - 1.10] Embedding & Upsert**: The chunks are passed to **FastEmbed** locally (CPU). The resulting dense/sparse vectors are inserted into **Qdrant** via gRPC, tagged with the `tenant_id`.

### 2.0 User Query Flow & Memory Management
When an End User submits a question via the chat interface:
- **[2.0 - 2.1] API Entry**: The End User types a query into the Web Client, which POSTs to `/api/query/stream`.
- **[2.2 - 2.3] Two-Tier Cache Check**: Before doing any heavy lifting, the API checks **Redis** [2.2] for an exact match, and if that fails, checks the **Qdrant semantic cache** [2.3].
- **[2.4 - 2.6] Ledger & History**: The user's query is committed to the **PostgreSQL `ChatMessage`** table. The `MemoryManager` fetches the past chat history.
- **[2.7 - 2.8] Memory Summarization**: If the historical text exceeds 4,000 tokens [2.7], an **8B Groq Summarizer** compresses older context. The context is fed into the `AgentWorkflow` engine [2.8].

### 3.0 Orchestration Flow (LangGraph DAG)
The internal LangGraph state machine orchestrates the actual RAG process:
- **[3.1] Planner (`WorkflowPlanner`)**: Evaluates the query using a fast 8B JSON-constrained model to determine if retrieval is needed.
- **[3.2a / 3.2b] Router & Rewriter**: Routes directly to a Chat Responder [3.2a] or to the Query Rewriter [3.2b] to resolve ambiguities and split sub-queries.
- **[3.3 - 3.4] Retrieval & Reranker**: Executes a hybrid search against Qdrant [3.3]. A Diversity Reranker [3.4] enforces semantic diversity.
- **[3.5 - 3.6b] Relevance Checker & Fallback**: The Relevance Checker strictly evaluates the chunks [3.5]. If insufficient, it hits the Fallback Rewriter [3.6a]. If it continually fails, it routes to Graceful Degradation [3.6b].
- **[3.6c - 3.7] Generator & Verifier (Actor-Critic)**: The **ResearchAgent** [3.6c] generates the answer using `<thinking>` tags. The **VerificationAgent** [3.7] independently verifies the draft against the raw chunks.
- **[3.8] Guardrail**: The final generated text passes through a PIIGuardrail [3.8].

### 4.0 SSE Streaming Output
As the LangGraph DAG executes, `astream_events` emits real-time status updates:
- **[4.0] Output Streaming**: The FastAPI server streams SSE back to the UI. When `<thinking>` tags are emitted, they are suppressed and hidden from the user.
- **[4.1] Rendering**: The Next.js Web Client renders the final polished markdown for the End User.
