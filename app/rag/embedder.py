"""
Embedder wrapper — sentence-transformers lokálisan, nincs API költség.
"""
from flask import current_app
import numpy as np


class Embedder:
    _model = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer
            model_name = current_app.config['EMBEDDING_MODEL']
            current_app.logger.info(f'Loading embedding model: {model_name}')
            cls._model = SentenceTransformer(model_name)
        return cls._model

    @classmethod
    def embed(cls, texts, normalize=True):
        """Embed one or more texts. Returns numpy array of vectors."""
        model = cls.get_model()
        # e5 models need 'query: ' or 'passage: ' prefix
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
        if 'e5' in current_app.config['EMBEDDING_MODEL'].lower():
            text = f'query: {text}'
        vec = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return np.array(vec[0], dtype=np.float32)


# Simple cosine similarity (no ChromaDB dependency for basic usage)
def cosine_similarity(a, b):
    a_norm = a / np.linalg.norm(a) if np.linalg.norm(a) > 0 else a
    b_norm = b / np.linalg.norm(b) if np.linalg.norm(b) > 0 else b
    return float(np.dot(a_norm, b_norm))