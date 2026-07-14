import sys
import os
import asyncio

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from agents.workflow import AgentWorkflow
from retriever.builder import RetrieverBuilder
from db.database import SessionLocal
from db.models import ChatThread, ChatMessage, User
from utils.memory import memory_manager

def run_evaluation():
    tenant_id = "default_tenant"
    thread_id = "eval_thread_" + os.urandom(4).hex()
    
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=tenant_id).first()
        if not user:
            db.add(User(id=tenant_id, email="eval@example.com", hashed_password="pw"))
            db.commit()

        thread = ChatThread(id=thread_id, user_id=tenant_id, title="Eval Thread")
        db.add(thread)
        db.commit()

        # Turn 1 (Given in context)
        q0 = "how Prompt Injection and Answer Generation works?"
        msg0 = ChatMessage(thread_id=thread_id, role="user", content=q0)
        db.add(msg0)
        
        ans0 = "The process of Prompt Injection and Answer Generation works by appending retrieved chunks to the user query, processing this combined prompt with a Large Language Model (LLM) to generate a response, and potentially including image IDs and handling tables in the generated answer."
        msg1 = ChatMessage(thread_id=thread_id, role="assistant", content=ans0)
        db.add(msg1)
        db.commit()

        queries_to_test = [
            {
                "query": "What language model did they use to generate the synthetic question-answer pairs for it?",
                "expected": "Mentions GPT-4o"
            },
            {
                "query": "How does that prompt injection formula compare to the step in the very first PDF I uploaded where they stop an employee's salary?",
                "expected": "Fail/Not Found (document missing)"
            },
            {
                "query": "You mentioned image and table recovery at the end of your last response. How exactly does the system store those tables in the database before recovering them?",
                "expected": "Dictionary-formatted tables / JSON-like"
            }
        ]

        retriever = RetrieverBuilder().build_hybrid_retriever(tenant_id=tenant_id, thread_id=None)
        workflow = AgentWorkflow()

        report_lines = ["# Regression Evaluation Report\n"]

        for q_idx, test_case in enumerate(queries_to_test):
            q = test_case["query"]
            expected = test_case["expected"]
            
            report_lines.append(f"## Query {q_idx + 1}")
            report_lines.append(f"**Original Query:** `{q}`")
            report_lines.append(f"**Expected Behavior:** {expected}\n")
            
            # Save User Message
            user_msg = ChatMessage(thread_id=thread_id, role="user", content=q)
            db.add(user_msg)
            db.commit()

            # 1. Memory
            past_messages = db.query(ChatMessage).filter(ChatMessage.thread_id == thread_id).order_by(ChatMessage.created_at.asc()).all()
            condensed_history = memory_manager.compress_history(past_messages[:-1]) # exclude the current one

            # 2. Planner & Rewriter
            decision = workflow.planner.plan(question=q, chat_history=condensed_history, attached_document_ids=[])
            rewritten_query = workflow.rewriter.rewrite(original_question=q, chat_history=condensed_history)
            
            report_lines.append(f"**Rewritten Query:** `{rewritten_query}`\n")

            # 3. Retriever
            documents = retriever.invoke(rewritten_query)
            reranked = workflow.reranker.rerank(rewritten_query, documents)
            
            report_lines.append(f"### Retrieved Chunks ({len(reranked)} after reranking)")
            for i, doc in enumerate(reranked):
                score = doc.metadata.get('rerank_score', 0.0)
                source = doc.metadata.get('source', 'Unknown')
                page = doc.metadata.get('page', 'Unknown')
                report_lines.append(f"- **Chunk {i+1}**: [Score: {score:.4f}] [Source: {source}] [Page: {page}]")
                snippet = doc.page_content.replace('\n', ' ')[:150]
                report_lines.append(f"  > {snippet}...")
            report_lines.append("")

            # 4. Prompt & Gen
            context = "\n\n".join([doc.page_content for doc in reranked])
            final_prompt = workflow.researcher.generate_prompt(question=q, context=context, chat_history=condensed_history)
            
            report_lines.append(f"### Final Prompt Snippet")
            report_lines.append("```text\n" + final_prompt[:500] + "\n...\n```\n")

            final_response = workflow.researcher.model.invoke(final_prompt)
            final_answer = final_response.content
            
            report_lines.append(f"### Final Generated Answer")
            report_lines.append(f"> {final_answer.replace(chr(10), chr(10)+'> ')}\n")
            
            report_lines.append("### Pass / Fail Assessment")
            report_lines.append("**Status:** [ ] PASS / [ ] FAIL *(Fill manually)*")
            report_lines.append("---\n")

            # Save Assistant Message
            agent_msg = ChatMessage(thread_id=thread_id, role="assistant", content=final_answer)
            db.add(agent_msg)
            db.commit()

        # Write to evaluation_report.md
        with open("evaluation_report.md", "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        print("Evaluation complete. Report written to evaluation_report.md")

    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    run_evaluation()
