import json
from pydantic import ValidationError
from backend.models import DocumentSummary
from backend import config
from groq import Groq

# will it run?
CLIENT = Groq(api_key=config.GROQ_KEY)
PROMPT = """You are a document summarizer. Respond ONLY with valid JSON in this exact format:
{
    "summary": "2-3 sentence summary of the document",
    "key_points": ["point 1", "point 2", "point 3"],
    "language": "English",
    "word_count": 150
}
Rules:
1. No other text
2. No explanation
3. Just JSON
4. Answer in the same language as the document"""

def call_llm(text: list[str]) -> DocumentSummary:

    for attempt in range(2):
        try:
            response = CLIENT.chat.completions.create(
                model='llama-3.1-8b-instant',
                messages=[
                    {'role': 'system', 'content': PROMPT},
                    {'role': 'user', 'content': text}
                ]
            )
            res_text = response.choices[0].message.content

            data = json.loads(res_text)
            return DocumentSummary(**data)
        
        except (json.JSONDecodeError, ValidationError):
            if attempt == 0:
                continue
            raise
    

def get_summary_from_llm(text_chunks: str) -> DocumentSummary:

    summaries = [call_llm(chunk) for chunk in text_chunks]

    if len(summaries) == 1:
        return summaries[0]
    
    combined = '\n\n'.join([s.summary for s in summaries])

    return call_llm(combined)