from flask import Flask, request, jsonify

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return "ok", 200

@app.post("/validate")
def validate():
    data = request.get_json(silent=True) or {}
    sentence = (data.get('sentence') or '').strip()

    # --- Your rules (edit/extend freely) ---
    if not sentence:
        return jsonify(valid=False, reason="Empty sentence")
    if "banned" in sentence.lower():
        return jsonify(valid=False, reason="Contains banned word")
    # more rules here...
    # ---------------------------------------

    return jsonify(valid=True)
