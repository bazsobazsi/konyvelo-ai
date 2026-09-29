"""
Accountant agent — könyvelő specifikus prompt RAG-gel.
"""
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

    def generate(self, messages, context_chunks=None):
        """
        Generate with RAG.
        messages: list of {'role': ..., 'content': ...}
        Returns: (response_text, sources_used)
        """
        # Get the last user message for search
        last_user_msg = ''
        for m in reversed(messages):
            if m['role'] == 'user':
                last_user_msg = m['content']
                break

        # Search for relevant documents
        if context_chunks is None:
            config = current_app.config
            top_k = config.get('RAG_TOP_K', 5)
            threshold = config.get('RAG_SIMILARITY_THRESHOLD', 0.45)
            context_chunks = search_documents(last_user_msg, top_k=top_k, threshold=threshold)

        # Build system prompt with context
        context_text = self.format_context(context_chunks)
        system_msg = self.SYSTEM_PROMPT
        if context_text:
            system_msg += '\n\n' + context_text
        else:
            system_msg += '\n\nFIGYELEM: Nincsenek betöltött források. Jelezd, hogy a dokumentumtár még nincs feltöltve.'

        # Build full message list
        full_messages = [{'role': 'system', 'content': system_msg}]
        full_messages.extend(messages)

        try:
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
                # Try reasoning field (DeepSeek models)
                content = choices[0].get('message', {}).get('reasoning', '') or ''

            # Return simplified sources for UI
            sources_out = []
            for c in context_chunks:
                sources_out.append({
                    'title': c.get('title', ''),
                    'source': c.get('source', ''),
                    'score': c.get('score', 0),
                    'year': c.get('year', ''),
                })

            return content, sources_out

        except requests.exceptions.Timeout:
            return '⏱️ Az AI nem válaszolt időben. Kérlek, próbáld újra.', []
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if hasattr(e, 'response') else '?'
            return f'❌ AI hiba (HTTP {status}). Próbáld újra később.', []
        except RuntimeError as e:
            return f'⚠️ {e}', []
        except Exception as e:
            current_app.logger.error(f'AI generate error: {e}')
            return '❌ Hiba történt az AI hívás közben.', []