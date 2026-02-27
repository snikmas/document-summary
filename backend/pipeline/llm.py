import json
import logging

from openai import OpenAI, APIStatusError
from pydantic import ValidationError
from backend.models import DocumentSummary
from backend import config

log = logging.getLogger("pipeline.llm")

if not config.OPEN_ROUTER_KEY:
    raise RuntimeError("OPEN_ROUTER is not set in .env")

CLIENT = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=config.OPEN_ROUTER_KEY,
    timeout=120.0,
)
# MODEL = 'google/gemini-2.0-flash-001'
MODEL = 'meta-llama/llama-3.3-70b-instruct:free'

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
    log.info("Calling LLM (%s) with %d chars", MODEL, len(text))

    for attempt in range(2):
        try:
            response = CLIENT.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": f"Document:\n{text}"},
                ],
            )
            log.info("Got response from LLM (attempt %d)", attempt + 1)
            res_text = response.choices[0].message.content.strip()
            if res_text.startswith("```"):
                res_text = res_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            data = json.loads(res_text)
            log.info("LLM response parsed successfully")
            return DocumentSummary(**data)

        except (json.JSONDecodeError, ValidationError) as e:
            log.warning("LLM parse attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                continue
            raise
        except APIStatusError as e:
            log.error("LLM API error (attempt %d): %s %s", attempt + 1, e.status_code, e.message)
            if e.status_code == 429:
                raise RuntimeError("AI service rate limited. Please try again in a moment.") from e
            elif e.status_code == 401:
                raise RuntimeError("AI service authentication failed. Please check your OPEN_ROUTER API key.") from e
            elif e.status_code == 402:
                raise RuntimeError("AI service requires credits. Please check your OpenRouter account.") from e
            elif e.status_code >= 500:
                raise RuntimeError("AI service is temporarily unavailable. Please try again later.") from e
            raise RuntimeError(f"AI service error: {e.message}") from e
        except Exception as e:
            log.error("LLM API error (attempt %d): %s: %s", attempt + 1, type(e).__name__, e)
            raise RuntimeError(f"Failed to get AI summary: {e}") from e


def get_summary_from_llm(text_chunks: list[str]) -> DocumentSummary:
    log.info("Summarizing %d chunk(s)", len(text_chunks))

    summaries = [call_llm(chunk) for chunk in text_chunks]

    if len(summaries) == 1:
        return summaries[0]

    log.info("Merging %d chunk summaries into final summary", len(summaries))
    combined = '\n\n'.join([s.summary for s in summaries])

    return call_llm(combined)
