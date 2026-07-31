import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


ROOT_DIR = Path(__file__).parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
INPUT_DIR = ROOT_DIR / "input"
OUTPUT_DIR = ROOT_DIR / "output"
PROMPTS_DIR = Path(__file__).parent / "analysis" / "prompts"

# Modèle LLM cible. Format litellm : "anthropic/...", "openai/...", "azure/..."
# ou nom court ("gpt-4o", "claude-sonnet-4-5-20250929"). Auto-détection du
# provider à partir du nom. Les clés API sont lues dans les variables
# d'environnement standard du provider (ANTHROPIC_API_KEY, OPENAI_API_KEY...).
LLM_MODEL: str = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-5")

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0"))
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "32768"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))

# Pour les modèles reasoning (gpt-5.4-mini, o3-mini, etc.) : low/medium/high.
# Laisser vide pour les modèles non-reasoning (gpt-4o, claude-*).
REASONING_EFFORT: str | None = os.getenv("REASONING_EFFORT") or None

GOLDEN_TEMPLATE_PATH = ASSETS_DIR / "golden-source-template-v2-templated.pptx"

# ── API : sécurité et concurrence ────────────────────────────────────────────
# Secret partagé qu'un appelant (Polaris) doit envoyer dans le header
# ``X-Shared-Secret`` pour atteindre /generate, /generate/pptx ou /jobs.
# Si vide (défaut), l'auth est désactivée — utile en dev / dans les tests.
CV_AGENT_SHARED_SECRET: str = os.getenv("CV_AGENT_SHARED_SECRET", "")

# Nombre de jobs traités simultanément par le ThreadPoolExecutor du serveur.
# Calé sur la rate-limit Anthropic et le footprint mémoire du rendering.
MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))
