from __future__ import annotations

from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8765"


class AnkiError(RuntimeError):
    pass


class AnkiUnavailableError(AnkiError):
    pass


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class AnkiClient:
    """Minimal async client for the AnkiConnect add-on (JSON-RPC v6)."""

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 8.0):
        self.url = url
        self.timeout = timeout

    async def _invoke(self, client: httpx.AsyncClient, action: str, **params: Any) -> Any:
        payload = {"action": action, "version": 6, "params": params}
        try:
            resp = await client.post(self.url, json=payload)
        except httpx.HTTPError as exc:
            raise AnkiUnavailableError(
                f"Cannot reach AnkiConnect at {self.url}. Is Anki running with the AnkiConnect add-on installed? ({exc})"
            ) from exc
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise AnkiError(f"AnkiConnect error on {action}: {data['error']}")
        return data.get("result")

    async def ping(self) -> int:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return int(await self._invoke(client, "version"))

    async def deck_names(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return list(await self._invoke(client, "deckNames"))

    async def model_names(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return list(await self._invoke(client, "modelNames"))

    async def field_names(self, model: str) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return list(await self._invoke(client, "modelFieldNames", modelName=model))

    async def find_notes(self, query: str) -> list[int]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return list(await self._invoke(client, "findNotes", query=query))

    async def notes_info(self, note_ids: list[int]) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return list(await self._invoke(client, "notesInfo", notes=note_ids))

    async def word_exists(
        self, word: str, translation: str, front_field: str, back_field: str
    ) -> bool:
        """True if a note exists whose front field equals `word` (and back field
        equals `translation` when a translation is given)."""
        ids = await self.find_notes(f'"{front_field}:{_escape_query(word)}"')
        if not ids:
            return False
        infos = await self.notes_info(ids)
        word_l = word.strip().lower()
        trans_l = translation.strip().lower()
        for note in infos:
            fields = note.get("fields", {})
            front = fields.get(front_field, {}).get("value", "").strip().lower()
            if front != word_l:
                continue
            if trans_l:
                back = fields.get(back_field, {}).get("value", "").strip().lower()
                if back == trans_l:
                    return True
            else:
                return True
        return False

    async def add_note(
        self, deck: str, model: str, fields: dict[str, str], tags: list[str] | None = None
    ) -> int:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return int(
                await self._invoke(
                    client,
                    "addNote",
                    note={
                        "deckName": deck,
                        "modelName": model,
                        "fields": fields,
                        "options": {"allowDuplicate": False},
                        "tags": tags or [],
                    },
                )
            )

    async def check_words(
        self,
        items: list[tuple[str, str]],
        front_field: str,
        back_field: str,
        progress=None,
    ) -> dict[str, bool]:
        """items: list of (word, translation). Returns {word: exists_in_anki}."""
        result: dict[str, bool] = {}
        for i, (word, translation) in enumerate(items):
            result[word] = await self.word_exists(word, translation, front_field, back_field)
            if progress:
                progress(i + 1, len(items))
        return result

    async def add_words(
        self,
        items: list[tuple[str, str]],
        deck: str,
        model: str,
        front_field: str,
        back_field: str,
        progress=None,
    ) -> tuple[int, list[str]]:
        """Add (word, translation) notes. Returns (added_count, list_of_errors)."""
        added = 0
        errors: list[str] = []
        for i, (word, translation) in enumerate(items):
            try:
                await self.add_note(deck, model, {front_field: word, back_field: translation}, tags=["ebook-vocab"])
                added += 1
            except AnkiError as exc:
                errors.append(f"{word}: {exc}")
            if progress:
                progress(i + 1, len(items))
        return added, errors
