from src.analysis.llm_client import LLMClient
from src.analysis.prompts import load_prompt
from src.analysis.vocabulary_frequency import compute_term_frequencies
from src.schemas import Brief, RawDocument


def extract_brief(ao: RawDocument, client: LLMClient | None = None) -> Brief:
    llm = client or LLMClient()
    system = load_prompt("extract_brief")
    user_message = (
        f"=== APPEL D'OFFRES (fichier : {ao.source_name}) ===\n\n{ao.text}\n"
    )
    brief = llm.call_structured(
        system=system,
        user_message=user_message,
        response_model=Brief,
    )
    return compute_term_frequencies(brief, ao.text)
