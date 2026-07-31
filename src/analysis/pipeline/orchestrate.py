from concurrent.futures import ThreadPoolExecutor

from src.analysis.gap_safety_net import apply_gap_safety_net
from src.analysis.llm_client import LLMClient
from src.analysis.pipeline.extract_brief import extract_brief
from src.analysis.pipeline.extract_cv import extract_cv
from src.analysis.pipeline.match_and_reformulate import match_and_reformulate
from src.schemas import AdaptedCV, RawDocument, RenderConstraints


def generate(
    cvs: list[RawDocument],
    ao: RawDocument,
    constraints: RenderConstraints,
    client: LLMClient | None = None,
) -> AdaptedCV:
    """Pipeline complet : 3 appels LLM dont 2 en parallèle.

    Étape 1 (parallèle) : Extract-Brief + Extract-CV.
    Étape 2 (séquentielle) : Match+Reformulate (sélection + rédaction).
    Étape 3 (déterministe) : garde-fou de remontée des besoins critiques
    non couverts, en filet de sécurité derrière la consigne de prompt.
    """
    llm = client or LLMClient()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_brief = pool.submit(extract_brief, ao, client=llm)
        f_raw_cv = pool.submit(extract_cv, cvs, client=llm)
        brief = f_brief.result()
        raw_cv = f_raw_cv.result()

    adapted_cv = match_and_reformulate(brief, raw_cv, constraints, client=llm)
    return apply_gap_safety_net(brief, raw_cv, adapted_cv)
