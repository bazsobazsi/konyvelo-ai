#!/usr/bin/env python3
"""
KönyvelőAI adatgyűjtő — futtatás: python3 collectors/run.py

Mit csinál:
  1. Letölti a NAV füzetek index-et + a szövegfájlokat
  2. Letölti a MK/Közlöny szövegeket
  3. Építi egy unifikált dokumentum index-et (data/documents.json)
  4. Érzékeli a változásokat
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Konfiguráció ──
DATA_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / 'data'
OUTPUT_INDEX = DATA_DIR / 'documents.json'
STATUS_FILE = DATA_DIR / 'collector_status.json'

NAV_INDEX_PATH = Path.home() / '.kozlony_figyelo' / 'nav_index.json'
NAV_TEXTS_DIR = Path.home() / '.kozlony_figyelo' / 'nav_texts'
MK_TEXTS_DIR = Path.home() / '.kozlony_figyelo' / 'texts'

# Egyezzen az app/config.py EMBEDDING_MODEL-lel
EMBEDDING_MODEL = 'intfloat/multilingual-e5-small'


def load_nav_documents():
    """Betölti a NAV füzeteket (metadata + szöveg)"""
    if not NAV_INDEX_PATH.exists():
        print("⚠ NAV index nem található")
        return []

    with open(NAV_INDEX_PATH, 'r', encoding='utf-8') as f:
        index = json.load(f)

    items = []
    for entry in index.get('fuzetek', []):
        text = ''
        text_file = entry.get('text_file', '')
        if text_file and os.path.exists(text_file):
            try:
                with open(text_file, 'r', encoding='utf-8', errors='ignore') as tf:
                    text = tf.read()
            except Exception as e:
                print(f"  ⚠ text_file hiba: {e}")

        items.append({
            'id': f"nav_{entry.get('number', '00')}",
            'title': entry.get('title', 'NAV füzet'),
            'text': text,
            'source': 'NAV információs füzet',
            'url': entry.get('url', ''),
            'year': str(entry.get('year', '')),
            'source_type': 'nav',
        })

    print(f"  NAV: {len(items)} dokumentum")
    return items


def load_mk_documents():
    """Betölti a MK szövegeket"""
    if not MK_TEXTS_DIR.is_dir():
        print("⚠ MK texts könyvtár nem létezik")
        return []

    txt_files = sorted([
        f for f in MK_TEXTS_DIR.glob('*.txt')
    ], key=lambda p: p.name)

    items = []
    for fpath in txt_files:
        try:
            text = fpath.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            print(f"  ⚠ {fpath.name}: {e}")
            continue

        fname = fpath.stem  # 2026_142_Magyar_Közlöny
        items.append({
            'id': f"mk_{fname}",
            'title': fname,
            'text': text,
            'source': 'Magyar Közlöny',
            'url': '',
            'year': fname.split('_')[0] if '_' in fname else '',
            'source_type': 'mk',
        })

    print(f"  MK: {len(items)} dokumentum")
    return items


def build_chunks(items, chunk_size=1500):
    """Széti a dokumentumokat kisebb chunk-okbe (a retriever hatáta 2000/napi)"""
    chunks = []
    for doc in items:
        text = doc.get('text', '')
        if not text.strip():
            continue
        for i in range(0, len(text), chunk_size):
            chunk_text = text[i:i + chunk_size]
            if len(chunk_text.strip()) < 100:
                continue
            chunks.append({
                'id': f"{doc['id']}_chunk{i}",
                'title': doc['title'],
                'text': chunk_text[:2000],  # cap
                'source': doc['source'],
                'url': doc['url'],
                'year': doc['year'],
                'source_type': doc.get('source_type', ''),
            })
    return chunks


def run():
    print(f"📊 KönyvelőAI adatgyűjtő — {datetime.now(timezone.utc).isoformat()}")
    t0 = time.time()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Betöltés
    docs = []
    docs.extend(load_nav_documents())
    docs.extend(load_mk_documents())
    print(f"\nÖsszesen: {len(docs)} dokumentum letöltve")

    # 2. Chunk generálás
    chunks = build_chunks(docs)
    print(f"Chunk-ok: {len(chunks)}")

    # 3. Index betöltés
    prev_chunks = []
    if OUTPUT_INDEX.exists():
        try:
            with open(OUTPUT_INDEX, 'r', encoding='utf-8') as f:
                prev = json.load(f)
                prev_chunks = prev.get('chunks', [])
        except Exception:
            pass

    # 4. Változás detekció
    new_ids = {c['id'] for c in chunks}
    old_ids = {c['id'] for c in prev_chunks}
    added = new_ids - old_ids
    removed = old_ids - new_ids

    # 5. Index frissítés
    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'total_documents': len(docs),
        'total_chunks': len(chunks),
        'added_chunks': len(added),
        'removed_chunks': len(removed),
        'sources': {
            'nav': sum(1 for d in docs if d.get('source_type') == 'nav'),
            'mk': sum(1 for d in docs if d.get('source_type') == 'mk'),
        },
        'chunks': chunks,
    }
    with open(OUTPUT_INDEX, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)

    # 5b. Embedding cache előre kiszámítása (ha van sentence-transformers)
    embeddings_built = False
    try:
        from app.rag.embedder import Embedder, _meta_for, _save_disk_cache
        if Embedder.is_available():
            print("🧠 Embeddingek előre számítása (egyszeri, cache-be)...")
            model_name = EMBEDDING_MODEL
            meta = _meta_for(chunks, model_name)
            vecs = Embedder.embed([c['text'][:1000] for c in chunks])
            _save_disk_cache(vecs, meta)
            embeddings_built = True
            print(f"   {vecs.shape[0]} vektor mentve (data/embeddings.npy)")
        else:
            print("ℹ sentence-transformers nincs telepítve — kulcsszó fallback lesz")
    except Exception as e:
        print(f"⚠ Embedding precompute hiba: {e}")

    # 6. Statisztika fájl
    elapsed = time.time() - t0
    status = {
        'last_run': datetime.now(timezone.utc).isoformat(),
        'last_run_local': datetime.now().strftime('%Y.%m.%d %H:%M'),
        'elapsed_seconds': round(elapsed, 1),
        'documents': len(docs),
        'chunks': len(chunks),
        'added': len(added),
        'removed': len(removed),
        'sources': output['sources'],
        'embeddings_cached': embeddings_built,
        'success': True,
    }
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Index elkészült ({round(elapsed, 1)} sec)")
    print(f"   Chunk változás: +{len(added)} / -{len(removed)}")
    print(f"   Időszak: {len(docs)} dokumentum → {len(chunks)} chunk")


if __name__ == '__main__':
    run()