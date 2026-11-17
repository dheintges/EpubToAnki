"""Smoke test for the core pipeline (not part of the app)."""
import asyncio
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.analyzer import (
    DEFAULT_MODEL,
    ModelNotInstalledError,
    count_lemmas,
    installed_models,
    load_model,
    top_words,
)
from core.anki import AnkiClient, AnkiUnavailableError
from core.reader import extract_text
from core.translator import Translator

SAMPLE = """The old man walked slowly along the river. He ran every morning and swam in the cold water.
Running was his favourite sport. His grandchildren ran around and laughed. He runs daily now, and ran yesterday too."""


def make_epub() -> bytes:
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_title("Test")
    c = epub.EpubHtml(title="ch1", file_name="ch1.xhtml", lang="en")
    c.content = "<p>The runner runs and ran fast. Berlin is nice.</p>"
    book.add_item(c)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc = [c]
    book.spine = ["nav", c]
    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def make_epub3_no_ncx() -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        z.writestr("OEBPS/content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title><dc:identifier id="id">x</dc:identifier></metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>""")
        z.writestr("OEBPS/nav.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol><li><a href="ch1.xhtml">Ch1</a></li></ol></nav></body></html>')
        z.writestr("OEBPS/ch1.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>The runner runs fast in Paris. Bonjour le monde.</p></body></html>')
    return buf.getvalue()


def make_pdf() -> bytes:
    content = b"BT /F1 24 Tf 100 700 Td (Hello running world from PDF) Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objs) + 1))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref))
    return out.getvalue()


class FakeAnki(BaseHTTPRequestHandler):
    notes = {"run": {"Front": "run", "Back": "laufen"}, "hello": {"Front": "hello", "Back": "hallo"}}
    added = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        action, params = body["action"], body.get("params", {})
        if action == "version":
            result = 6
        elif action == "deckNames":
            result = ["Default"]
        elif action == "modelNames":
            result = ["Basic"]
        elif action == "modelFieldNames":
            result = ["Front", "Back"]
        elif action == "findNotes":
            q = params["query"]
            word = q.split(":", 1)[1].strip('"')
            result = [1000 + i for i, w in enumerate(self.notes) if w == word.lower()]
        elif action == "notesInfo":
            result = [
                {"noteId": nid, "fields": {k: {"value": v} for k, v in self.notes[w].items()}}
                for i, w in enumerate(self.notes) for nid in [1000 + i] if nid in params["notes"]
            ]
        elif action == "addNote":
            self.added.append(params["note"])
            result = 2000 + len(self.added)
        else:
            result = None
        payload = json.dumps({"result": result, "error": None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def test_reader():
    txt = extract_text(SAMPLE.encode(), ".txt")
    assert "river" in txt
    epub_txt = extract_text(make_epub(), ".epub")
    assert "runner" in epub_txt and "<p>" not in epub_txt, epub_txt
    pdf_txt = extract_text(make_pdf(), ".pdf")
    assert "running" in pdf_txt, repr(pdf_txt)
    epub3 = extract_text(make_epub3_no_ncx(), ".epub")
    assert "Bonjour le monde" in epub3 and "Ch1" not in epub3, repr(epub3[:200])
    try:
        extract_text(b"not a zip", ".epub")
        raise AssertionError("broken epub should raise")
    except ValueError as exc:
        assert "Could not parse epub" in str(exc)
    print("reader OK | pdf text:", repr(pdf_txt.strip()), "| epub3-no-ncx OK")


def test_analyzer():
    counter = count_lemmas(SAMPLE)
    assert counter["run"] == 5, counter.most_common(8)  # ran, Running, ran, runs, ran
    assert counter["walk"] == 1
    assert "the" in counter  # stopwords kept by default
    c2 = count_lemmas(SAMPLE, drop_propn=True, drop_stopwords=True, min_len=3)
    assert "the" not in c2
    top = top_words(counter, min_freq=1, max_words=5)
    assert len(top) == 5 and top[0][1] >= top[-1][1]
    print("analyzer OK | run count:", counter["run"], "| top:", top[:5])


def test_models():
    models = installed_models()
    assert DEFAULT_MODEL in models, models
    nlp = load_model(DEFAULT_MODEL)
    assert nlp("running").__iter__  # loads and caches
    assert load_model(DEFAULT_MODEL) is nlp  # cached
    try:
        load_model("definitely_not_a_real_model_xyz")
        raise AssertionError("missing model should raise")
    except ModelNotInstalledError as exc:
        assert "python -m spacy download" in str(exc)
    from core.analyzer import download_model
    try:
        download_model("definitely_not_a_real_model_xyz")
        raise AssertionError("bad download should raise")
    except RuntimeError as exc:
        assert "failed" in str(exc).lower()
    counter = count_lemmas("He runs and ran.", nlp=nlp)
    assert counter["run"] == 2
    print("models OK | installed:", models)


def test_translator():
    # Live Google endpoint is IP-rate-limited from this sandbox; verify logic with a stub.
    tr = Translator.__new__(Translator)

    class FlakyTR:
        def __init__(self):
            self.calls = 0

        def translate(self, w):
            self.calls += 1
            if self.calls < 3:
                raise Exception("boom")
            return {"hello": "hallo", "world": "welt"}[w]

    tr._tr = FlakyTR()
    out = tr.translate_many(["hello", "world"], delay=0)
    assert out == {"hello": "hallo", "world": "welt"}, out

    class BadTR:
        def translate(self, w):
            raise Exception("always fails")

    tr._tr = BadTR()
    out2 = tr.translate_many(["x"], delay=0)
    assert out2 == {"x": ""}, out2

    try:
        Translator("deepl", "en", "de", "")
        raise AssertionError("deepl without key should raise")
    except ValueError:
        pass
    print("translator OK (stubbed; live Google endpoint rate-limited from this sandbox)")


async def test_anki():
    server = HTTPServer(("127.0.0.1", 0), FakeAnki)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = AnkiClient(f"http://127.0.0.1:{port}")
    assert await client.ping() == 6
    assert await client.deck_names() == ["Default"]
    assert await client.field_names("Basic") == ["Front", "Back"]
    assert await client.word_exists("run", "laufen", "Front", "Back") is True
    assert await client.word_exists("run", "WRONG", "Front", "Back") is False
    assert await client.word_exists("nonexistent", "", "Front", "Back") is False
    added, errors = await client.add_words([("walk", "gehen"), ("swim", "schwimmen")], "Default", "Basic", "Front", "Back")
    assert added == 2 and not errors
    assert FakeAnki.added[0]["fields"] == {"Front": "walk", "Back": "gehen"}
    server.shutdown()
    dead = AnkiClient("http://127.0.0.1:1", timeout=1)
    try:
        await dead.ping()
        raise AssertionError("should have raised")
    except AnkiUnavailableError:
        pass
    print("anki OK | added:", len(FakeAnki.added))


if __name__ == "__main__":
    test_reader()
    test_analyzer()
    test_models()
    test_translator()
    asyncio.run(test_anki())
    print("ALL CORE TESTS PASSED")
