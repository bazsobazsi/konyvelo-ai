#!/usr/bin/env python3
"""
Embedding előszámítás build időben (avagy manuálisan).

Beolvassa a data/documents.json-t, kiszámolja a chunk vektorokat és kiírja:
  precomputed/embeddings.npy
  precomputed/embeddings_meta.json

Így az első felhasználói keresés nem számolja újra a 6000+ chunk embeddingjét.

Használat:
  python3 collectors/precompute_embeddings.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL_NAME = 'intfloat/multilingual-e5-small'
DOCS = ROOT / 'data' / 'documents.json'
OUT_DIR = ROOT / 'precomputed'


def main():
    if not DOCS.exists():
        print(f'❌ Nincs {DOCS} — előbb futtasd a collectors/run.py-t.')
        return 1

    with open(DOCS, 'r', encoding='utf-8') as f:
        data = json.load(f)
    chunks = data.get('chunks', [])
    if not chunks:
        print('❌ Nincs chunk a documents.json-ban.')
        return 1

    import numpy as np
    from sentence_transformers import SentenceTransformer
    from app.rag.embedder import _meta_for

    print(f'🧠 Modell betöltése: {MODEL_NAME}')
    model = SentenceTransformer(MODEL_NAME)

    texts = [f"passage: {(c.get('text') or '')[:1000]}" for c in chunks]
    print(f'🔢 {len(texts)} chunk embeddingje...')
    vecs = model.encode(texts, normalize_embeddings=True,
                        show_progress_bar=True, batch_size=64)
    vecs = np.array(vecs, dtype=np.float32)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.save(OUT_DIR / 'embeddings.npy', vecs)
    with open(OUT_DIR / 'embeddings_meta.json', 'w', encoding='utf-8') as f:
        json.dump(_meta_for(chunks, MODEL_NAME), f)

    print(f'✅ Kész: {vecs.shape} -> {OUT_DIR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
