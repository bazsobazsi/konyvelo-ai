"""
Embedder — lokális embedding, API-költség nélkül.
Ha sentence-transformers nincs telepítve, fallback: kulcsszó egyezés.

A chunk-ok vektorait lemezen cache-eljük (data/embeddings.npy), hogy a keresés
ne számolja újra minden kérésnél a 6000+ chunk embeddingjét.
"""
from flask import current_app
import numpy as np
import os
import re
import json
import logging

logger = logging.getLogger(__name__)

# Ha nincs torch/sentence-transformers, False-ra áll
_st_available = False
try:
    from sentence_transformers import SentenceTransformer
    _st_available = True
except ImportError:
    logger.warning("sentence-transformers nem elérhető — kulcsszó-alapú keresés lesz a fallback")


# ── Lemezes embedding cache ──

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
PRECOMPUTED_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'precomputed'))

# Cache helyek prioritási sorrendben:
#  1. data/ (perzisztens volume — a collector ide ír)
#  2. precomputed/ (build időben előre számolva, az image-be égetve)
EMB_CACHE_CANDIDATES = [
    (os.path.join(DATA_DIR, 'embeddings.npy'), os.path.join(DATA_DIR, 'embeddings_meta.json')),
    (os.path.join(PRECOMPUTED_DIR, 'embeddings.npy'), os.path.join(PRECOMPUTED_DIR, 'embeddings_meta.json')),
]
EMB_CACHE_NPY, EMB_CACHE_META = EMB_CACHE_CANDIDATES[0]

_MEM = {'ids': None, 'vecs': None}


def _meta_for(chunks, model_name):
    import hashlib
    h = hashlib.sha256()
    h.update(model_name.encode())
    for c in chunks:
        h.update(str(c['id']).encode('utf-8', 'ignore'))
        h.update(b'|')
    return {'model': model_name, 'count': len(chunks), 'ids_hash': h.hexdigest()}


def _load_disk_cache(meta_wanted):
    for npy_path, meta_path in EMB_CACHE_CANDIDATES:
        if not (os.path.exists(npy_path) and os.path.exists(meta_path)):
            continue
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            if meta.get('ids_hash') != meta_wanted['ids_hash'] or meta.get('model') != meta_wanted['model']:
                continue
            vecs = np.load(npy_path)
            if vecs.shape[0] != meta_wanted['count']:
                continue
            logger.info(f'Embedding cache betöltve innen: {npy_path} {vecs.shape}')
            return vecs.astype(np.float32)
        except Exception as e:
            logger.warning(f'Embedding cache betöltés hiba ({npy_path}): {e}')
    return None


def _save_disk_cache(vecs, meta_wanted):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        np.save(EMB_CACHE_NPY, vecs)
        with open(EMB_CACHE_META, 'w', encoding='utf-8') as f:
            json.dump(meta_wanted, f)
        logger.info(f'Embedding cache mentve: {vecs.shape}')
    except Exception as e:
        logger.warning(f'Embedding cache mentés hiba: {e}')


class Embedder:
    _model = None

    @classmethod
    def _model_name(cls):
        """App kontextus nélkül is működik (pl. a collector CLI-ból fut)."""
        try:
            return current_app.config['EMBEDDING_MODEL']
        except Exception:
            return 'intfloat/multilingual-e5-small'

    @classmethod
    def is_available(cls):
        return _st_available

    @classmethod
    def get_model(cls):
        if not _st_available:
            return None
        if cls._model is None:
            model_name = cls._model_name()
            logger.info(f'Loading embedding model: {model_name}')
            cls._model = SentenceTransformer(model_name)
        return cls._model

    @classmethod
    def embed(cls, texts, normalize=True):
        """Embed one or more texts. Returns numpy array of vectors."""
        model = cls.get_model()
        if model is None:
            return np.zeros((len(texts), 4), dtype=np.float32)
        if 'e5' in cls._model_name().lower():
            texts = [f'passage: {t}' if isinstance(t, str) and len(t) > 0 else t for t in texts]
        vectors = model.encode(texts, normalize_embeddings=normalize,
                               show_progress_bar=False, batch_size=32)
        return np.array(vectors, dtype=np.float32)

    @classmethod
    def embed_query(cls, text):
        """Embed a single query (with query prefix for e5 models)."""
        model = cls.get_model()
        if model is None:
            return np.zeros(4, dtype=np.float32)
        if 'e5' in cls._model_name().lower():
            text = f'query: {text}'
        vec = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return np.array(vec[0], dtype=np.float32)


def get_chunk_vectors(chunks):
    """Chunk vektorok: memória -> lemez cache -> számítás (egyszer).

    Ez a kulcs a gyors kereséshez: a 6000+ chunk embeddingjét NEM számoljuk
    minden kérésnél újra.
    """
    if not _st_available or not chunks:
        return None

    model_name = Embedder._model_name()
    ids = [c['id'] for c in chunks]

    if _MEM['ids'] == ids and _MEM['vecs'] is not None:
        return _MEM['vecs']

    meta_wanted = _meta_for(chunks, model_name)
    vecs = _load_disk_cache(meta_wanted)
    if vecs is None:
        logger.info(f'Embeddingek számítása {len(chunks)} chunkra (egyszeri, utána cache)...')
        vecs = Embedder.embed([c['text'][:1000] for c in chunks])
        _save_disk_cache(vecs, meta_wanted)

    _MEM['ids'] = ids
    _MEM['vecs'] = vecs
    return vecs


# Cosine similarity
def cosine_similarity(a, b):
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── Keyword fallback ──

_STOPWORDS = {
    'a', 'az', 'és', 'hogy', 'is', 'nem', 'azt', 'egy', 'meg', 'ha',
    'be', 'el', 'ki', 'fel', 'le', 'át', 'de', 'mi', 'már', 'még',
    'van', 'vagy', 'csak', 'mint', 'ezt', 'ez', 'olyan', 'mely', 'aki',
}


def keyword_score(query: str, text: str) -> float:
    """Szóátfedés alapú pontszám (tf-szerű), embedding nélkül."""
    q_words = set(re.findall(r'\w+', query.lower()))
    t_words = set(re.findall(r'\w+', text.lower()))
    if not q_words or not t_words:
        return 0.0
    q_words -= _STOPWORDS
    if not q_words:
        return 0.0
    return len(q_words & t_words) / len(q_words)


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
