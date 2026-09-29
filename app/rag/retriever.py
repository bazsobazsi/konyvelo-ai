"""
Retriever — ChromaDB alapú vektor keresés a dokumentumok között.
Fallback: JSON index fájl ha ChromaDB nincs inicializálva.
"""
import json
import os
import numpy as np
from flask import current_app
from app.rag.embedder import Embedder, cosine_similarity

# In-memory cache for doc chunks when Chroma is not ready
_doc_cache = None


def get_document_chunks():
    """Load document chunks from JSON index (NAV füzetek + MK szövegek)."""
    global _doc_cache
    if _doc_cache is not None:
        return _doc_cache

    chunks = []

    # 1. NAV füzetek index
    nav_index_path = os.path.expanduser('~/.kozlony_figyelo/nav_index.json')
    if os.path.exists(nav_index_path):
        try:
            with open(nav_index_path, 'r', encoding='utf-8') as f:
                nav_data = json.load(f)
            if isinstance(nav_data, list):
                for item in nav_data:
                    text = item.get('full_text', item.get('text', ''))
                    if text:
                        chunks.append({
                            'id': f"nav_{item.get('id', item.get('title', ''))}",
                            'title': item.get('title', 'NAV füzet'),
                            'text': text[:2000],  # chunk size limit
                            'source': 'NAV információs füzet',
                            'url': item.get('url', ''),
                            'year': item.get('year', ''),
                        })
        except Exception:
            pass

    # 2. MK szövegek (directory scan)
    texts_dir = os.path.expanduser('~/.kozlony_figyelo/texts/')
    if os.path.isdir(texts_dir):
        txt_files = sorted(os.listdir(texts_dir))[-50:]  # last 50
        for fname in txt_files:
            if not fname.endswith('.txt'):
                continue
            fpath = os.path.join(texts_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                # Chunk large texts
                fname_base = fname.replace('.txt', '')
                for i in range(0, len(text), 1500):
                    chunk_text = text[i:i + 1500]
                    if len(chunk_text.strip()) < 100:
                        continue
                    chunks.append({
                        'id': f"mk_{fname_base}_{i}",
                        'title': fname_base,
                        'text': chunk_text,
                        'source': 'Magyar Közlöny',
                        'url': '',
                        'year': fname_base.split('_')[0] if '_' in fname_base else '',
                    })
            except Exception:
                pass

    _doc_cache = chunks
    current_app.logger.info(f'Loaded {len(chunks)} document chunks')
    return chunks


def search_documents(query, top_k=5, threshold=0.45):
    """
    Search documents by cosine similarity.
    Returns list of {'title', 'text', 'source', 'url', 'score', 'year'}
    """
    chunks = get_document_chunks()
    if not chunks:
        return []

    query_vec = Embedder.embed_query(query)

    # Get embeddings for all chunks (cache-friendly)
    texts = [c['text'][:1000] for c in chunks]
    chunk_vecs = Embedder.embed(texts)

    results = []
    for i, chunk in enumerate(chunks):
        score = cosine_similarity(query_vec, chunk_vecs[i])
        if score >= threshold:
            results.append({
                'title': chunk['title'],
                'text': chunk['text'][:800],
                'source': chunk['source'],
                'url': chunk['url'],
                'score': round(score, 3),
                'year': chunk.get('year', ''),
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_k]