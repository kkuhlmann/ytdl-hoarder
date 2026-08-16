from functools import lru_cache

from fastapi import Request

from config import settings
from logger import logger
from services.embeddings import OnnxEmbedder


def sanitize_folder_name(name: str) -> str:
    """Sanitize a string for use as a directory name.

    Removes filesystem-unsafe characters, strips leading/trailing dots and spaces,
    and truncates to 100 characters. Returns "Unknown" if the result is empty.
    """
    unsafe_chars = '/\\:*?"<>|\0'
    sanitized = ''.join(c for c in name if c not in unsafe_chars)
    # Leading/trailing dots and spaces are problematic on Windows and some filesystems
    sanitized = sanitized.strip('. ')
    sanitized = sanitized[:100]
    return sanitized or 'Unknown'


@lru_cache(maxsize=1)
def load_embedding_model() -> OnnxEmbedder:
    return OnnxEmbedder(settings.embedding.model)


def get_model(request: Request) -> OnnxEmbedder:
    model = getattr(request.app.state, 'embedding_model', None)
    if model is None:
        logger.info('No embedding model found, loading...')
        model = load_embedding_model()
        request.app.state.embedding_model = model
    return model
