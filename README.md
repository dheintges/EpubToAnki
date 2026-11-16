# eBook → Anki Vocabulary Builder

A local Python app with a [NiceGUI](https://nicegui.io) web interface that turns an
eBook into new vocabulary flashcards for Anki.

Pipeline:

1. **Read** the eBook — `.pdf` (pypdf), `.epub` (ebooklib), or plain `.txt`.
2. **Tokenize + lemmatize** with spaCy — "running", "ran", "runs" all count as `run`.
3. **Count** lemma frequencies (`collections.Counter`).
4. **Translate** every unique word (Google Translate via `deep-translator`, free;
   or DeepL with your API key).
5. **Check Anki** via the [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
   add-on — words that already exist in your deck (same word *and* translation)
   are filtered out.
6. **Add** the remaining new words to Anki as flashcards, or export them as CSV.

## Setup

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

## Run

```bash
python app.py
```

Then open http://127.0.0.1:8080 in your browser.

## Anki setup

- Install the **AnkiConnect** add-on in Anki (Tools → Add-ons → Get Add-ons → code `2055492159`), then restart Anki.
- Anki must be running while you use steps 3–4. The app talks to AnkiConnect at
  `http://localhost:8765` from the Python backend, so no browser CORS config is needed.
- In the app, pick your deck, note model (e.g. `Basic`), and which fields hold the
  word and the translation (defaults: `Front` / `Back`).

## Usage

1. Upload an eBook (or press **Load sample text** to try it out).
2. Adjust analysis options (drop proper nouns, min frequency, max words).
3. Choose source/target language and translation provider.
4. Press **1 · Analyze eBook**, then **2 · Translate**, then **3 · Check Anki**,
   then **4 · Add new to Anki** — or just **Run all**.
5. **Export CSV** downloads the final list of new words with counts and translations.

## Project layout

```
app.py               NiceGUI user interface
core/reader.py       eBook text extraction (.pdf / .epub / .txt)
core/analyzer.py     spaCy tokenization, lemmatization, frequency counting
core/translator.py   translation backends (Google free / DeepL)
core/anki.py         async AnkiConnect client (find, check, add notes)
```

## Notes

- The free Google provider uses the unofficial endpoint behind `deep-translator` and
  may rate-limit on very large word lists; the app retries and continues on errors.
  For production-quality translation, use the `deepl` provider with your API key.
- spaCy's English model is used for lemmatization. For other source languages,
  download the matching model (e.g. `de_core_news_sm`) and adjust
  `core/analyzer.py:get_nlp`.
