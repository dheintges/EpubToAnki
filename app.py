from __future__ import annotations

import asyncio
import csv
import io
from collections import Counter
from dataclasses import dataclass, field

from nicegui import app, run, ui

from core.analyzer import chunk_text, count_lemmas, get_nlp, top_words
from core.anki import AnkiClient, AnkiError, AnkiUnavailableError
from core.reader import SUPPORTED_SUFFIXES, extract_text
from core.translator import PROVIDERS, Translator

LANGUAGES = [
    "en", "de", "es", "fr", "it", "pt", "nl", "pl", "ru", "uk", "cs", "sv",
    "da", "fi", "no", "tr", "ar", "ja", "ko", "zh-CN", "hi", "id", "vi", "th",
]

SAMPLE_TEXT = """The old man walked slowly along the river. He was thinking about his youth,
when he ran every morning and swam in the cold water. Running had always been his
favourite sport, but now his knees hurt. His grandchildren ran around him and laughed.
"Why do you run so fast?" they asked. He smiled and said, "Because I still can."
The sun set behind the hills, and the man went home. He cooked dinner, read a book,
and thought about tomorrow. Tomorrow he would walk again, slowly but happily."""


@dataclass
class State:
    filename: str = ""
    text: str = ""
    counter: Counter = field(default_factory=Counter)
    words: list[tuple[str, int]] = field(default_factory=list)
    translations: dict[str, str] = field(default_factory=dict)
    anki: dict[str, str] = field(default_factory=dict)  # word -> "yes"/"no"/"unknown"
    busy: bool = False


state = State()
anki = AnkiClient()


def log(msg: str) -> None:
    log_widget.push(msg)


def set_busy(busy: bool) -> None:
    state.busy = busy
    for btn in step_buttons:
        btn.disable() if busy else btn.enable()


def refresh_table() -> None:
    rows = []
    for word, count in state.words:
        rows.append({
            "id": word,
            "word": word,
            "count": count,
            "translation": state.translations.get(word, ""),
            "anki": state.anki.get(word, "—"),
        })
    table.rows = rows
    table.update()
    new_count = sum(1 for w, _ in state.words if state.anki.get(w) == "no")
    stats_label.text = (
        f"{len(state.words)} unique lemmas · {sum(state.counter.values())} tokens · "
        f"{len(state.translations)} translated · {new_count} new (not in Anki)"
    )


async def load_file(name: str, data: bytes) -> None:
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in SUPPORTED_SUFFIXES:
        ui.notify(f"Unsupported format {suffix!r}. Supported: {sorted(SUPPORTED_SUFFIXES)}", type="negative")
        return
    state.text = extract_text(data, suffix)
    state.filename = name
    state.counter.clear()
    state.words = []
    state.translations.clear()
    state.anki.clear()
    file_label.text = f"Loaded: {name} ({len(data) / 1024:.0f} KB, {len(state.text)} chars)"
    log(f"Extracted {len(state.text)} characters from {name}")
    progress.value = 0
    refresh_table()
    ui.notify(f"Loaded {name}", type="positive")


async def on_upload(e) -> None:
    data = e.content.read()
    await load_file(e.name, data)


def load_sample() -> None:
    state.text = SAMPLE_TEXT
    state.filename = "sample.txt"
    state.counter.clear()
    state.words = []
    state.translations.clear()
    state.anki.clear()
    file_label.text = "Loaded: sample text (built-in)"
    log("Loaded built-in sample text")
    progress.value = 0
    refresh_table()


async def do_analyze() -> None:
    if not state.text:
        ui.notify("Upload an eBook or load the sample text first.", type="warning")
        return
    set_busy(True)
    log("Analyzing text (tokenize + lemmatize with spaCy)...")
    progress.value = 0
    try:
        counter: Counter = Counter()
        chunks = list(chunk_text(state.text))
        for i, chunk in enumerate(chunks):
            part = await run.io_bound(
                count_lemmas,
                chunk,
                drop_propn=drop_propn.value,
                drop_stopwords=drop_stop.value,
                min_len=int(min_len.value or 2),
            )
            counter.update(part)
            progress.value = (i + 1) / len(chunks)
            await asyncio.sleep(0.01)
        state.counter = counter
        max_words = int(max_words_input.value or 0) or None
        state.words = top_words(counter, min_freq=int(min_freq.value or 1), max_words=max_words)
        log(f"Found {len(state.words)} unique lemmas ({sum(counter.values())} tokens)")
        refresh_table()
        ui.notify(f"Analysis done: {len(state.words)} unique lemmas", type="positive")
    except Exception as exc:
        log(f"Analysis failed: {exc}")
        ui.notify(f"Analysis failed: {exc}", type="negative")
    finally:
        set_busy(False)


async def do_translate() -> None:
    if not state.words:
        ui.notify("Run '1. Analyze' first.", type="warning")
        return
    provider = provider_select.value
    try:
        translator = Translator(
            provider,
            source_lang.value,
            target_lang.value,
            deepl_key=deepl_input.value or "",
        )
    except ValueError as exc:
        ui.notify(str(exc), type="negative")
        return
    set_busy(True)
    log(f"Translating {len(state.words)} words {source_lang.value} -> {target_lang.value} via {provider}...")
    progress.value = 0
    try:
        words = [w for w, _ in state.words]
        done = 0
        group_size = 25
        for start in range(0, len(words), group_size):
            group = words[start:start + group_size]
            result = await run.io_bound(translator.translate_many, group, None, 0.03)
            state.translations.update(result)
            done += len(group)
            progress.value = done / len(words)
            refresh_table()
            await asyncio.sleep(0.01)
        log(f"Translated {len(state.translations)} words")
        ui.notify("Translation done", type="positive")
    except Exception as exc:
        log(f"Translation failed: {exc}")
        ui.notify(f"Translation failed: {exc}", type="negative")
    finally:
        set_busy(False)


async def anki_available() -> bool:
    try:
        version = await anki.ping()
        log(f"AnkiConnect reachable (API version {version})")
        return True
    except AnkiUnavailableError as exc:
        log(str(exc))
        ui.notify("AnkiConnect not reachable — Anki steps skipped. Start Anki with the AnkiConnect add-on.", type="warning", timeout=8000)
        return False


async def do_check_anki() -> None:
    if not state.words:
        ui.notify("Run '1. Analyze' first.", type="warning")
        return
    if not await anki_available():
        for w, _ in state.words:
            state.anki[w] = "unknown"
        refresh_table()
        return
    set_busy(True)
    log("Checking words against Anki deck...")
    progress.value = 0
    try:
        items = [(w, state.translations.get(w, "")) for w, _ in state.words]

        def on_progress(done: int, total: int) -> None:
            progress.value = done / total if total else 1

        result = await anki.check_words(items, front_field.value, back_field.value, progress=on_progress)
        state.anki.update({w: ("yes" if exists else "no") for w, exists in result.items()})
        new_count = sum(1 for v in result.values() if not v)
        log(f"Anki check done: {new_count} of {len(items)} words are new")
        refresh_table()
        ui.notify(f"{new_count} new words not in Anki", type="positive")
    except AnkiError as exc:
        log(f"Anki check failed: {exc}")
        ui.notify(str(exc), type="negative")
    finally:
        set_busy(False)


async def do_add_to_anki() -> None:
    new_items = [(w, state.translations.get(w, "")) for w, _ in state.words if state.anki.get(w) == "no"]
    if not new_items:
        ui.notify("No new words to add — run '3. Check Anki' first.", type="warning")
        return
    if not await anki_available():
        return
    set_busy(True)
    log(f"Adding {len(new_items)} notes to deck '{deck_select.value}'...")
    progress.value = 0
    try:
        def on_progress(done: int, total: int) -> None:
            progress.value = done / total if total else 1

        added, errors = await anki.add_words(
            new_items, deck_select.value, model_select.value, front_field.value, back_field.value, progress=on_progress
        )
        for w, _ in new_items:
            state.anki[w] = "added"
        log(f"Added {added} notes" + (f"; {len(errors)} errors: {errors[:5]}" if errors else ""))
        refresh_table()
        ui.notify(f"Added {added} notes to Anki" + (f", {len(errors)} failed" if errors else ""), type="positive")
    except AnkiError as exc:
        log(f"Adding notes failed: {exc}")
        ui.notify(str(exc), type="negative")
    finally:
        set_busy(False)


async def run_all() -> None:
    await do_analyze()
    if state.words:
        await do_translate()
        await do_check_anki()


def export_csv() -> None:
    rows = [(w, c, state.translations.get(w, "")) for w, c in state.words if state.anki.get(w) in ("no", "unknown", "")]
    if not rows:
        ui.notify("Nothing to export — no words selected as new.", type="warning")
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["word", "count", "translation"])
    writer.writerows(rows)
    ui.download(buf.getvalue().encode("utf-8"), "new_words.csv", media_type="text/csv")
    log(f"Exported {len(rows)} words to new_words.csv")


async def refresh_anki_meta() -> None:
    if not await anki_available():
        return
    try:
        decks = await anki.deck_names()
        models = await anki.model_names()
        deck_select.options = decks
        model_select.options = models
        if not deck_select.value and decks:
            deck_select.value = decks[0]
        if not model_select.value and models:
            model_select.value = "Basic" if "Basic" in models else models[0]
        fields = await anki.field_names(model_select.value)
        field_select.options = fields
        if front_field.value not in fields and fields:
            front_field.value = fields[0]
        if back_field.value not in fields:
            back_field.value = fields[1] if len(fields) > 1 else (fields[0] if fields else "")
        deck_select.update()
        model_select.update()
        front_field.update()
        back_field.update()
        log(f"Anki meta loaded: {len(decks)} decks, {len(models)} models, fields={fields}")
    except AnkiError as exc:
        ui.notify(str(exc), type="negative")


def on_model_change() -> None:
    async def update_fields():
        try:
            fields = await anki.field_names(model_select.value)
            field_select.options = fields
            if front_field.value not in fields and fields:
                front_field.value = fields[0]
            if back_field.value not in fields:
                back_field.value = fields[1] if len(fields) > 1 else (fields[0] if fields else "")
            field_select.update()
            front_field.update()
            back_field.update()
        except AnkiError:
            pass

    from nicegui import background_tasks
    background_tasks.create(update_fields())


with ui.header().classes("items-center gap-4"):
    ui.label("📚 eBook → Anki Vocabulary Builder").classes("text-2xl font-bold")
    ui.space()
    anki_status = ui.label("Anki: not checked").classes("text-sm opacity-70")

with ui.row().classes("w-full gap-4 items-start"):
    with ui.card().classes("w-96 shrink-0"):
        ui.label("1 · Source eBook").classes("text-lg font-semibold")
        file_label = ui.label("No file loaded").classes("text-sm opacity-70")
        with ui.row().classes("w-full"):
            ui.upload(label="Upload eBook (.pdf/.epub/.txt)", auto_upload=True,
                      max_file_size=100 * 1024 * 1024, on_upload=on_upload).classes("w-full")
        ui.button("Load sample text", on_click=load_sample).props("outline")

        ui.separator()
        ui.label("2 · Analysis").classes("text-lg font-semibold")
        drop_propn = ui.checkbox("Drop proper nouns (names)", value=True)
        drop_stop = ui.checkbox("Drop stopwords (the, and, ...)", value=False)
        with ui.row().classes("w-full"):
            min_freq = ui.number("Min frequency", value=1, min=1, step=1).classes("w-1/2")
            min_len = ui.number("Min word length", value=2, min=1, step=1).classes("w-1/2")
        max_words_input = ui.number("Max words (0 = all)", value=500, min=0, step=50).classes("w-full")

        ui.separator()
        ui.label("3 · Translation").classes("text-lg font-semibold")
        with ui.row().classes("w-full"):
            source_lang = ui.select(LANGUAGES, value="en", label="Source language").classes("w-1/2")
            target_lang = ui.select(LANGUAGES, value="de", label="Target language").classes("w-1/2")
        provider_select = ui.select(PROVIDERS, value="google-free", label="Provider").classes("w-full")
        deepl_input = ui.input("DeepL API key (only for deepl provider)", password=True,
                               password_toggle_button=True).classes("w-full")

        ui.separator()
        ui.label("4 · Anki (AnkiConnect)").classes("text-lg font-semibold")
        with ui.row().classes("w-full"):
            ui.button("Connect / refresh", on_click=refresh_anki_meta).props("outline size=sm")
        deck_select = ui.select([], label="Deck", with_input=True).classes("w-full")
        model_select = ui.select([], label="Note model", with_input=True)
        model_select.on_value_change(on_model_change)
        with ui.row().classes("w-full"):
            front_field = ui.select(["Front"], label="Front field (word)", with_input=True).classes("w-1/2")
            back_field = ui.select(["Back"], label="Back field (translation)", with_input=True).classes("w-1/2")

    with ui.column().classes("flex-1 gap-2 min-w-0"):
        with ui.row().classes("w-full gap-2"):
            step_buttons = [
                ui.button("1 · Analyze eBook", on_click=do_analyze),
                ui.button("2 · Translate", on_click=do_translate),
                ui.button("3 · Check Anki", on_click=do_check_anki),
                ui.button("4 · Add new to Anki", on_click=do_add_to_anki),
                ui.button("Run all", on_click=run_all).props("color=secondary"),
                ui.button("Export CSV", on_click=export_csv).props("outline"),
            ]
        progress = ui.linear_progress(value=0).classes("w-full")
        stats_label = ui.label("No analysis yet").classes("text-sm opacity-70")
        table = ui.table(
            columns=[
                {"name": "word", "label": "Word (lemma)", "field": "word", "sortable": True, "align": "left"},
                {"name": "count", "label": "Count", "field": "count", "sortable": True},
                {"name": "translation", "label": "Translation", "field": "translation", "align": "left"},
                {"name": "anki", "label": "In Anki?", "field": "anki", "sortable": True},
            ],
            rows=[],
            row_key="id",
            pagination=25,
        ).classes("w-full")
        with ui.expansion("Log", icon="terminal").classes("w-full"):
            log_widget = ui.log(max_lines=200).classes("w-full h-48")

ui.dark_mode(True)

if __name__ in {"__main__", "__mp_main__"}:
    get_nlp()  # load spaCy model once at startup
    ui.run(title="eBook → Anki Vocabulary Builder", host="127.0.0.1", port=8080, show=False, reload=False)
