import os
import time
import csv
import io
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIG ---
BASE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1qkDyAhlFBDZ8psV5WdUvDHA4a-62Rg-0376uug3Q1qE/export?format=csv&gid="
TAB_GIDS = {
    "es": "428782464",   # Spanish tab
    "fr": "1262524342"   # French tab
}
CACHE_TTL_SECONDS = 300

# Column headers in your sheet
H_LESSON = "#"
H_TOPIC = "Topic"
H_WORDNUM = "Word #"
H_WORD = "Learned Word"
H_S_PREFIX = "Sentence"
H_S_SUFFIX = "(Learning)"

CACHE = {
    "csv": {},
    "ts": {},
    "rows": {},
    "words_ordered": {}
}

def is_sentence_header(h):
    return h.startswith(H_S_PREFIX) and h.endswith(H_S_SUFFIX)

def load_csv_raw(lang, force=False):
    if lang not in TAB_GIDS:
        raise ValueError(f"Unsupported language: {lang}")
    now = time.time()
    if not force and lang in CACHE["csv"] and now - CACHE["ts"].get(lang, 0) < CACHE_TTL_SECONDS:
        return CACHE["csv"][lang]
    url = BASE_SHEET_URL + TAB_GIDS[lang]
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.content.decode("utf-8", errors="ignore")
        CACHE["csv"][lang] = data
        CACHE["ts"][lang] = now
        return data
    except Exception as e:
        print(f"[ERROR] Failed to fetch Google Sheet for {lang}: {e}")
        return None  # fail safe

def parse_rows(lang, force=False):
    data = load_csv_raw(lang, force=force)
    if data is None:
        return None, []
    reader = csv.reader(io.StringIO(data))
    rows = list(reader)
    headers = [h.strip() for h in rows[0]]
    header_index = {h: i for i, h in enumerate(headers)}
    sentence_headers = [h for h in headers if is_sentence_header(h)]

    def get(row, key):
        i = header_index.get(key)
        return (row[i].strip() if i is not None and i < len(row) else "")

    parsed = []
    for r in rows[1:]:
        if not any(r):
            continue
        parsed.append({
            "lesson": get(r, H_LESSON),
            "topic": get(r, H_TOPIC),
            "word_num": get(r, H_WORDNUM),
            "word": get(r, H_WORD),
            "sentences": [r[header_index[h]].strip() if header_index[h] < len(r) else "" for h in sentence_headers]
        })

    CACHE["rows"][lang] = parsed
    return parsed, sentence_headers

def build_ordered_vocab(lang, force=False):
    rows, _ = parse_rows(lang, force=force)
    if rows is None:
        return None
    def word_key(r):
        try:
            return int(r["word_num"])
        except:
            return 999999
    rows_sorted = sorted([r for r in rows if r["word"]], key=word_key)
    words, seen = [], set()
    for r in rows_sorted:
        w = r["word"].strip()
        lw = w.lower()
        if w and lw not in seen:
            words.append(w)
            seen.add(lw)
    CACHE["words_ordered"][lang] = words
    return words

def get_allowed_up_to(lang, cap=None, force=False):
    words = CACHE["words_ordered"].get(lang) or build_ordered_vocab(lang, force=force)
    if words is None:
        return None, None
    if cap is None:
        return words, len(words) - 1
    if isinstance(cap, int):
        idx = max(0, min(cap, len(words)-1))
        return words[:idx+1], idx
    try:
        idx = next(i for i, w in enumerate(words) if w.lower() == str(cap).strip().lower())
        return words[:idx+1], idx
    except StopIteration:
        return words, len(words) - 1

@app.get("/healthz")
def healthz():
    return "ok", 200

@app.post("/refreshVocabulary")
def refresh_vocabulary():
    data = request.get_json(silent=True) or {}
    lang = data.get("lang", "").lower()
    if lang not in TAB_GIDS:
        return jsonify(error="Invalid or missing language (use 'es' or 'fr')"), 400
    if parse_rows(lang, force=True)[0] is None:
        return jsonify(error="Could not fetch Google Sheet"), 500
    if build_ordered_vocab(lang, force=True) is None:
        return jsonify(error="Could not build vocabulary"), 500
    return jsonify(refreshed=True, size=len(CACHE["words_ordered"][lang])), 200

@app.post("/getGenerationState")
def get_generation_state():
    data = request.get_json(silent=True) or {}
    lang = data.get("lang", "").lower()
    if lang not in TAB_GIDS:
        return jsonify(valid=False, reason="Invalid or missing language (use 'es' or 'fr')"), 400

    cap = data.get("cap", None)

    allowed, idx = get_allowed_up_to(lang, cap)
    if allowed is None:
        return jsonify(valid=False, reason="Could not fetch allowed words — Google Sheet unavailable."), 200

    topics_hist = sorted(set(r["topic"] for r in CACHE["rows"].get(lang, []) if r["topic"]))
    prior = [s for r in CACHE["rows"].get(lang, []) for s in r["sentences"] if s]
    return jsonify(
        valid=True,
        allowed_vocabulary=allowed,
        learned_upto_index=idx,
        topics_history=topics_hist,
        prior_sentences=prior
    )

@app.post("/validate")
def validate():
    data = request.get_json(silent=True) or {}
    lang = data.get("lang", "").lower()
    if lang not in TAB_GIDS:
        return jsonify(valid=False, reason="Invalid or missing language (use 'es' or 'fr')"), 400

    sentence = (data.get('sentence') or '').strip()
    if not sentence:
        return jsonify(valid=False, reason="Empty sentence"), 200

    words = build_ordered_vocab(lang)
    if words is None:
        return jsonify(valid=False, reason="Could not fetch allowed words — Google Sheet unavailable."), 200

    return jsonify(valid=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
