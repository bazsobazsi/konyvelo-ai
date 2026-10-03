"""
Accountant agent — könyvelő specifikus prompt RAG-gel.
"""
import requests
from app.agents.base import BaseAgent
from app.rag.retriever import search_documents
from flask import current_app


class AccountantAgent(BaseAgent):
    SYSTEM_PROMPT = """Te egy tapasztalt magyar könyvelő asszisztens vagy.

SZABÁLYOK:
1. CSAK a megadott FORRÁSOK (--- FELHASZNÁLHATÓ FORRÁSOK ---) alapján válaszolj. Ne használj saját tudást.
2. Minden állítás után ADD MEG a forrást: [Forrás X: Cím]
3. Ha nincs releváns információ a források között, írd: "Nem találok erről információt a rendelkezésre álló dokumentumokban."
4. Tartsd a választ tömör, szakszerű stílusban.
5. Ha jogszabályszámot említesz, ellenőrizd, hogy szerepel-e a források között.
6. Használhatsz rövid idézeteket a forrásokból, de mindig idézőjelek között.

A felhasználó könyvelő, aki adózási, jövedéki, vám, társasági jogi és számviteli kérdésekben keres választ."""

    # ── Közös előkészítés: RAG keresés + prompt összeállítás ──

    def _prepare(self, messages, context_chunks=None):
        """Visszaad: (full_messages, sources_out, has_sources)"""
        last_user_msg = ''
        for m in reversed(messages):
            if m['role'] == 'user':
                last_user_msg = m['content']
                break

        if context_chunks is None:
            config = current_app.config
            top_k = config.get('RAG_TOP_K', 5)
            threshold = config.get('RAG_SIMILARITY_THRESHOLD', 0.45)
            context_chunks = search_documents(last_user_msg, top_k=top_k, threshold=threshold)

        context_text = self.format_context(context_chunks)
        system_msg = self.SYSTEM_PROMPT
        if context_text:
            system_msg += '\n\n' + context_text
        else:
            system_msg += '\n\nFIGYELEM: Nincsenek betöltött források. Jelezd, hogy a dokumentumtár még nincs feltöltve.'

        full_messages = [{'role': 'system', 'content': system_msg}]
        full_messages.extend(messages)

        sources_out = []
        for c in context_chunks:
            sources_out.append({
                'title': c.get('title', ''),
                'source': c.get('source', ''),
                'score': c.get('score', 0),
                'year': c.get('year', ''),
                'url': c.get('url', ''),
            })

        return full_messages, sources_out

    # ── Nem-streaming (fallback / kompatibilitás) ──

    def generate(self, messages, context_chunks=None):
        try:
            full_messages, sources_out = self._prepare(messages, context_chunks)
            data = self._call_openrouter(full_messages)

            if 'error' in data:
                err = data['error']
                if isinstance(err, dict):
                    err = err.get('message', str(err))
                return f'❌ OpenRouter hiba: {err}', []

            choices = data.get('choices', [])
            if not choices:
                return '⚠️ Az AI nem adott választ.', []

            content = choices[0].get('message', {}).get('content', '') or ''
            if not content:
                content = choices[0].get('message', {}).get('reasoning', '') or ''

            return content, sources_out

        except requests.exceptions.Timeout:
            return '⏱️ Az AI nem válaszolt időben. Kérlek, próbáld újra.', []
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if getattr(e, 'response', None) is not None else '?'
            return f'❌ AI hiba (HTTP {status}). Próbáld újra később.', []
        except RuntimeError as e:
            return f'⚠️ {e}', []
        except Exception as e:
            current_app.logger.error(f'AI generate error: {e}', exc_info=True)
            return '❌ Hiba történt az AI hívás közben.', []

    # ── Streaming ──

    def prepare_stream(self, messages, context_chunks=None):
        """Előkészítés streameléshez. Visszaad: (full_messages, sources_out)."""
        return self._prepare(messages, context_chunks)

    def stream_tokens(self, full_messages):
        """Token generator. Hibát RuntimeError-ként dob (a route elkapja)."""
        yield from self._call_openrouter_stream(full_messages)
