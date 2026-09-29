#!/usr/bin/env python3
"""
Collector — betölti a meglévő NAV füzeteket és MK szövegeket a RAG adatbázisba.
Futtatás: python3 collectors/init_index.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Flask context needed for config
from app import create_app
from app.rag.embedder import Embedder
from app.rag.retriever import get_document_chunks
import json

app = create_app()

with app.app_context():
    print("🔄 Dokumentumok betöltése...")
    chunks = get_document_chunks()
    print(f"   {len(chunks)} chunk betöltve")

    # Quick test: embed a test query
    print("🔄 Embedding modell betöltése...")
    test_vec = Embedder.embed_query("tao kulcs 2025")
    print(f"   Embedding dimenzió: {len(test_vec)}")

    # Test search
    print("\n🔄 Teszt keresés: 'társasági adó mértéke'")
    from app.rag.retriever import search_documents
    results = search_documents("társasági adó mértéke", top_k=3, threshold=0.3)
    for r in results:
        print(f"   [{r['source']}] {r['title']} (score: {r['score']})")
        text_preview = r['text'][:150].replace('\n', ' ')
        print(f"   {text_preview}...")

    print("\n✅ Index elkészült!")
    print(f"   Teljes chunk szám: {len(chunks)}")
    print(f"   Használható források: NAV füzetek + MK szövegek")