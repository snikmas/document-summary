import json
from pydantic import ValidationError
from backend.models import DocumentSummary
from backend import config
from google import genai

if not config.GEMINI_KEY:
    raise RuntimeError("GEMINI_KEY is not set in .env")

CLIENT = genai.Client(api_key=config.GEMINI_KEY)
MODEL = 'gemini-2.0-flash'

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

def call_llm(text: str) -> DocumentSummary:

    for attempt in range(2):
        try:
            response = CLIENT.models.generate_content(
                model=MODEL,
                contents=f"{PROMPT}\n\nDocument:\n{text}"
            )
            res_text = response.text.strip()
            if res_text.startswith("```"):
                res_text = res_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            data = json.loads(res_text)
            return DocumentSummary(**data)

        except (json.JSONDecodeError, ValidationError):
            if attempt == 0:
                continue
            raise


def get_summary_from_llm(text_chunks: list[str]) -> DocumentSummary:

    summaries = [call_llm(chunk) for chunk in text_chunks]

    if len(summaries) == 1:
        return summaries[0]

    combined = '\n\n'.join([s.summary for s in summaries])

    return call_llm(combined)
