import os
import time
import csv
import io
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIG ---
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1JgTqPghb1ThmpMKsvv4w3BA5TWTQP-yvA5mt2r3OjLc/export?format=csv&gid=339331513"
CACHE_TTL_SECONDS = 300  # 5 min cache

# Column headers in your sheet
H_LESSON = "#"
H_TOPIC = "Topic"
H_WORDNUM = "Word #"
H_WORD = "Learned Word"
H_S_PREFIX = "Sentence"
H_S_SUFFIX = "(Learning)"

CACHE = {"csv": None, "ts": 0, "rows": [], "words_ordered": []}

def is_sentence_header(h):
    return h.startswith(H_S_PREFIX) and h.endswith(H_S_SUFFIX)

def load_csv_raw(force=False):
    now = time.time()
    if not force and CACHE["csv"] and now - CACHE["ts"] < CACHE_TTL_SECONDS:
        return CACHE["csv"]
    resp = requests.get(SHEET_CSV_URL, timeout=10)
    resp.raise_for_status()
    data = resp.content.decode("utf-8", errors="ignore")
    CACHE["csv"] = data
    CACHE["ts"] = now
    return data

def parse_rows(force=False):
    data = load_csv_raw(force=force)
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

    CACHE["rows"] = parsed
    return parsed, sentence_headers

def build_ordered_vocab(force=False):
    rows, _ = parse_rows(force=force)
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
    CACHE["words_ordered"] = words
    return words

def get_allowed_up_to(cap=None, force=False):
    words = CACHE["words_ordered"] or build_ordered_vocab(force=force)
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
    parse_rows(force=True)
    build_ordered_vocab(force=True)
    return jsonify(refreshed=True, size=len(CACHE["words_ordered"])), 200

@app.post("/getGenerationState")
def get_generation_state():
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    cap = data.get("cap", None)
    max_targets = int(data.get("max_targets", 5))

    allowed, idx = get_allowed_up_to(cap)
    topics_hist = sorted(set(r["topic"] for r in CACHE["rows"] if r["topic"]))
    prior = [s for r in CACHE["rows"] for s in r["sentences"] if s]
    return jsonify(
        allowed_vocabulary=allowed,
        learned_upto_index=idx,
        topics_history=topics_hist,
        prior_sentences=prior
    )

@app.post("/validate")
def validate():
    data = request.get_json(silent=True) or {}
    sentence = (data.get('sentence') or '').strip()
    if not sentence:
        return jsonify(valid=False, reason="Empty sentence")
    return jsonify(valid=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
