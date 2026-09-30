"""
Embedder — lokális embedding, API-költség nélkül.
Ha sentence-transformers nincs telepítve, fallback: kulcsszó egyezés.
"""
from flask import current_app
import numpy as np
import re
import logging

logger = logging.getLogger(__name__)

# Ha nincs torch/sentence-transformers, False-ra áll
_st_available = False
try:
    from sentence_transformers import SentenceTransformer
    _st_available = True
except ImportError:
    logger.warning("sentence-transformers nem elérhető — kulcsszó-alapú keresés lesz a fallback")


class Embedder:
    _model = None

    @classmethod
    def is_available(cls):
        return _st_available

    @classmethod
    def get_model(cls):
        if not _st_available:
            return None
        if cls._model is None:
            model_name = current_app.config['EMBEDDING_MODEL']
            logger.info(f'Loading embedding model: {model_name}')
            cls._model = SentenceTransformer(model_name)
        return cls._model

    @classmethod
    def embed(cls, texts, normalize=True):
        """Embed one or more texts. Returns numpy array of vectors."""
        model = cls.get_model()
        if model is None:
            return np.zeros((len(texts), 4), dtype=np.float32)
        if 'e5' in current_app.config['EMBEDDING_MODEL'].lower():
            prefixed = []
            for t in texts:
                prefixed.append(f'passage: {t}' if isinstance(t, str) and len(t) > 0 else t)
            texts = prefixed
        vectors = model.encode(texts, normalize_embeddings=normalize, show_progress_bar=False)
        return np.array(vectors, dtype=np.float32)

    @classmethod
    def embed_query(cls, text):
        """Embed a single query (with query prefix for e5 models)."""
        model = cls.get_model()
        if model is None:
            return np.zeros(4, dtype=np.float32)
        if 'e5' in current_app.config['EMBEDDING_MODEL'].lower():
            text = f'query: {text}'
        vec = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return np.array(vec[0], dtype=np.float32)


# Cosine similarity
def cosine_similarity(a, b):
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── Keyword fallback ──

def keyword_score(query: str, text: str) -> float:
    """Szóátfedés alapú pontszám (tf-szerű), embedding nélkül."""
    q_words = set(re.findall(r'\w+', query.lower()))
    t_words = set(re.findall(r'\w+', text.lower()))
    if not q_words or not t_words:
        return 0.0
    # Magyar jogi sztop szavak szűrése
    stopwords = {'a', 'az', 'és', 'hogy', 'is', 'nem', 'azt', 'egy', 'meg', 'ha',
                 'be', 'el', 'ki', 'fel', 'le', 'át', 'de', 'mi', 'már', 'még'}
    q_words -= stopwords
    if not q_words:
        return 0.0
    overlap = len(q_words & t_words) / len(q_words)
    return overlap


def search_keyword(query: str, chunks: list, top_k: int = 5, threshold: float = 0.3):
    """Kulcsszó-alapú keresés (embedding fallback)."""
    results = []
    for chunk in chunks:
        score = keyword_score(query, chunk['text'])
        if score >= threshold:
            results.append({
                'title': chunk['title'],
                'text': chunk['text'][:800],
                'source': chunk['source'],
                'url': chunk.get('url', ''),
                'score': round(score, 3),
                'year': chunk.get('year', ''),
            })
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_k]