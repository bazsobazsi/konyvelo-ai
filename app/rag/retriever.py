"""
Retriever — vektor keresés a dokumentumok között.
Ha sentence-transformers nincs, automatikus kulcsszó-fallback.
"""
import json
import os
from flask import current_app
from app.rag.embedder import Embedder, cosine_similarity, search_keyword

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
                            'text': text[:2000],
                            'source': 'NAV információs füzet',
                            'url': item.get('url', ''),
                            'year': item.get('year', ''),
                        })
        except Exception:
            pass

    # 2. MK szövegek (directory scan)
    texts_dir = os.path.expanduser('~/.kozlony_figyelo/texts/')
    if os.path.isdir(texts_dir):
        txt_files = sorted(os.listdir(texts_dir))[-50:]
        for fname in txt_files:
            if not fname.endswith('.txt'):
                continue
            fpath = os.path.join(texts_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
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
    """Search documents — embedding-based ha elérhető, egyébként kulcsszó."""
    chunks = get_document_chunks()
    if not chunks:
        return []

    if Embedder.is_available():
        # Vector search
        query_vec = Embedder.embed_query(query)
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
                    'url': chunk.get('url', ''),
                    'score': round(score, 3),
                    'year': chunk.get('year', ''),
                })
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]
    else:
        # Keyword fallback (lower threshold for keyword matching)
        return search_keyword(query, chunks, top_k=top_k, threshold=0.25)