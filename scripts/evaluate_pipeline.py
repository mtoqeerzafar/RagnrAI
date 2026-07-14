import os
import sys
import json
import asyncio
import pandas as pd
from typing import List, Dict
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import settings

class EvaluationScore(BaseModel):
    faithfulness: float = Field(description="Score between 0.0 and 1.0 indicating if the answer is derived strictly from the context.")
    answer_relevancy: float = Field(description="Score between 0.0 and 1.0 indicating if the answer addresses the question.")
    reasoning: str = Field(description="Brief reasoning for the assigned scores.")

async def evaluate_single(llm: ChatGroq, data: Dict) -> Dict:
    q = data["question"]
    a = data["expected_answer"]
    c = data["context"]
    
    prompt = f"""You are an expert evaluator for an AI RAG pipeline.
Please evaluate the following Question, Answer, and Contexts based on two metrics:
1. Faithfulness (0.0 to 1.0): Is the answer entirely based on the provided Contexts? (No hallucinations).
2. Answer Relevancy (0.0 to 1.0): Does the answer directly address the Question?

Question: {q}
Answer: {a}
Contexts: {c}
"""
    try:
        structured_llm = llm.with_structured_output(EvaluationScore)
        result: EvaluationScore = await structured_llm.ainvoke(prompt)
        return {
            "question": q,
            "faithfulness": result.faithfulness,
            "answer_relevancy": result.answer_relevancy,
            "reasoning": result.reasoning,
            "error": None
        }
    except Exception as e:
        return {
            "question": q,
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "reasoning": f"Failed: {str(e)}",
            "error": str(e)
        }

async def run_evaluation():
    print("Setting up Groq Evaluation Engine...")
    
    if not settings.GROQ_API_KEYS:
        print("Error: GROQ_API_KEYS is not set.")
        return
        
    llm = ChatGroq(
        api_key=settings.GROQ_API_KEYS.split(',')[0].strip(),
        model_name="llama-3.3-70b-versatile",
        temperature=0.0
    )
    
    test_data_path = os.path.join(os.path.dirname(__file__), "..", "tests", "test_data.json")
    if not os.path.exists(test_data_path):
        print(f"Error: test data not found at {test_data_path}")
        return
        
    with open(test_data_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print(f"Evaluating {len(dataset)} items...")
    
    # Run evaluations concurrently
    tasks = [evaluate_single(llm, item) for item in dataset]
    results = await asyncio.gather(*tasks)
    
    # Process results
    total_f = 0.0
    total_r = 0.0
    successful = 0
    
    for r in results:
        if not r["error"]:
            total_f += r["faithfulness"]
            total_r += r["answer_relevancy"]
            successful += 1
            print(f"✅ Q: '{r['question'][:30]}...' -> F: {r['faithfulness']}, R: {r['answer_relevancy']} | {r['reasoning']}")
        else:
            print(f"❌ Q: '{r['question'][:30]}...' -> Error: {r['error']}")
            
    if successful > 0:
        avg_f = total_f / successful
        avg_r = total_r / successful
        print("\n================== EVALUATION RESULTS ==================")
        print(f"Overall Average Faithfulness: {avg_f:.2f}")
        print(f"Overall Average Answer Relevancy: {avg_r:.2f}")
        print("========================================================")
        
    # Save to CSV
    try:
        import pandas as pd
        df = pd.DataFrame(results)
        out_path = os.path.join(os.path.dirname(__file__), "evaluation_report.csv")
        df.to_csv(out_path, index=False)
        print(f"Report saved to {out_path}")
    except ImportError:
        print("pandas not installed, skipping CSV export")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
