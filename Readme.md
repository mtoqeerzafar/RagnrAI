# RagnrAI ⚡

RagnrAI is a multi-agent Retrieval-Augmented Generation (RAG) system built using **Google Gemini**, **Docling**, and **LangGraph** to deliver accurate, verified answers from documents with built-in fact-checking.

---

## 🌟 Why RagnrAI?

Traditional LLMs struggle with large, complex documents that include tables, images, and dense text. Common issues include:

* ❌ Missing important details
* ❌ Generating incorrect or fake information
* ❌ Misreading structured data like tables
* ❌ Limited context handling

**RagnrAI solves this** using a multi-agent pipeline that ensures every response is grounded and verified.

---

## 🚀 Key Features

### 🧠 Multi-Agent System

* **Relevance Checker** – Confirms if documents can answer the query
* **Research Agent** – Generates initial responses
* **Verification Agent** – Validates answers against source documents
* **Auto Correction** – Re-runs process if inconsistencies are found

### 🔎 Hybrid Retrieval

* **BM25 Search** – Keyword-based matching
* **Vector Search** – Semantic understanding
* **Ensemble Method** – Combines both for better accuracy

### 📄 Document Processing

* Powered by **Docling**
* Supports OCR (scanned files)
* Handles PDF, DOCX, TXT, Markdown
* Smart caching to avoid reprocessing

### 💻 Interface

* Built with **Gradio**
* Simple and interactive UI
* Real-time answer verification

---

## 📦 Installation

### Prerequisites

* Python 3.9+
* Google API Key

### Setup

```bash
git clone https://github.com/your-username/RagnrAI.git
cd RagnrAI

python -m venv venv

# Activate
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

### Environment Variables

Create `.env` file:

```env
GOOGLE_API_KEY=your_api_key_here
```

---

## ⚡ Quick Start

```bash
python app.py
```

Open: `http://127.0.0.1:5000`

### Steps:

1. Upload documents
2. Enter your question
3. Submit
4. View answer + verification

---

## 📁 Project Structure

```
RAGNR-AI/
├── agents/
├── config/
├── document_processor/
├── retriever/
├── utils/
├── examples/
├── test/
├── document_cache/
├── chroma_db/
├── app.py
├── requirements.txt
├── .env
└── README.md
```

---

## ⚙️ Configuration

### `.env`

```env
GOOGLE_API_KEY=your_api_key
CHROMA_DB_PATH=./chroma_db
VECTOR_SEARCH_K=10
LOG_LEVEL=INFO
CACHE_DIR=document_cache
```

---

## 📖 Usage (Code)

```python
from document_processor.file_handler import DocumentProcessor
from retriever.builder import RetrieverBuilder
from agents.workflow import AgentWorkflow

processor = DocumentProcessor()
retriever_builder = RetrieverBuilder()
workflow = AgentWorkflow()

chunks = processor.process(files)
retriever = retriever_builder.build_hybrid_retriever(chunks)

result = workflow.full_pipeline(
    question="Your question",
    retriever=retriever
)

print(result["draft_answer"])
print(result["verification_report"])
```

---

## 🧠 How It Works

### 1. Processing

```
Upload → Parse → Split → Store
```

### 2. Retrieval

```
Query → BM25 + Vector → Ranked Results
```

### 3. Agents Workflow

```
Question → Relevance Check → Research → Verification → Final Answer
```

If errors are found → system retries automatically.

---

## 🔑 API Key Setup

1. Go to Google AI Studio
2. Create API Key
3. Add to `.env`

---

## 🐛 Troubleshooting

* Install dependencies:

  ```bash
  pip install -r requirements.txt
  ```

* Clear cache:

  ```bash
  rm -rf chroma_db/ document_cache/
  ```

* Check API key in `.env`

---

## 🤝 Contributing

1. Fork repo
2. Create branch
3. Commit changes
4. Push
5. Open PR

---

## 📝 License

MIT License

---

## 🙌 Credits

* Docling
* LangGraph
* Google Gemini
* Gradio
* ChromaDB

---

**RagnrAI — Smart, Verified Document Intelligence ⚡**
