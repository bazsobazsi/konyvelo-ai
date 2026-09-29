"""
Base agent — OpenRouter hívás RAG körrel.
"""
import requests
import json
from flask import current_app


class BaseAgent:
    SYSTEM_PROMPT = """Te egy szakértő asszisztens vagy."""

    def _call_openrouter(self, messages, stream=False):
        api_key = current_app.config['OPENROUTER_API_KEY']
        model = current_app.config['OPENROUTER_MODEL']
        base_url = current_app.config['OPENROUTER_BASE_URL']

        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY nincs beállítva. Állítsd be a .env fájlban vagy Coolify env vars-ben.")

        resp = requests.post(
            f'{base_url}/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model,
                'messages': messages,
                'max_tokens': 2048,
                'temperature': 0.3,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def generate(self, messages, context_chunks=None):
        """Generate response with optional RAG context."""
        raise NotImplementedError

    @staticmethod
    def format_context(chunks):
        """Format RAG chunks into a context string for the prompt."""
        if not chunks:
            return ''
        lines = ['\n--- FELHASZNÁLHATÓ FORRÁSOK ---']
        for i, c in enumerate(chunks, 1):
            source_label = f"{c.get('source', 'Ismeretlen')}"
            title = c.get('title', '')
            year = c.get('year', '')
            meta = f'[{source_label}]'
            if title:
                meta += f' {title}'
            if year:
                meta += f' ({year})'
            lines.append(f'\nForrás {i}: {meta}')
            lines.append(c.get('text', ''))
        lines.append('\n--- FORRÁSOK VÉGE ---')
        return '\n'.join(lines)