#!/usr/bin/env python3
"""Muse Sermon chatbot server. Stdlib only, Python 3.9+.

Run:   python3 server.py            (then open http://localhost:8000)
Works with no API key: the engine asks the questions (MODE: engine).
With ANTHROPIC_API_KEY set, an LLM writes the conversational replies, but the
engine record (stage, notes, flags, exigency) stays the source of truth and the
"write my sermon" request is always declined by the engine, never the LLM.
"""
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import muse_sermon as ms

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
SYSTEM = (ROOT / "SYSTEM_PROMPT.md").read_text(encoding="utf-8")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("MUSE_MODEL", "claude-sonnet-5-5")
SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_BODY = 20000
PERSONA = os.environ.get("MUSE_PERSONA", "Mother Tammy")
SASS = {
    "agenda": "Mm-hm. That sounds like your point, not the text’s. Show me the verse where it says that.",
    "certainty": "“Obviously” is doing a lot of work in that sentence. What does that reading depend on, and who reads it differently?",
    "application_early": "You’re running to the application before the text has finished talking. Sit with it first.",
    "cheap_inspiration": "“They did it, so we can” is cheap inspiration, baby. What did they get right, and what did they miss?",
    "cheap_despair": "Careful now. Name the specific thing and the specific history without lumping it all together.",
    "no_anchor": "Which verse is that sitting on? Give me chapter and verse.",
}
ACKS = ["Mm-hm. Go on.", "Alright, I’m listening.", "Say more.", "Hold on to that.", "Okay. Now let me push you.", "Keep going."]
REFUSAL = ("Now you know I can’t write it for you. That sermon has got to be yours. "
           "I can help you think through the structure, the exegesis, and the pastoral application. What part are you stuck on?")
PERSONA_RULES = (f"Speak as {PERSONA}, a seasoned church mother: warm, direct, a little sass, quick to call out when the "
                 "preacher’s agenda has replaced the text. Put the attitude in word choice, never in phonetic dialect spelling. "
                 "Never mock the preacher, the congregation, or the tradition. Never flatter. Say the hard thing kindly.")


# ------------------------------------------------------------ storage
def load(sid):
    p = DATA / f"{sid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(sid, s):
    (DATA / f"{sid}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def new_state(title, text, denomination, congregation):
    tradition = ms.DEFAULT_TRADITION + (f", {denomination}" if denomination else "")
    return {"title": title, "text": text, "tradition": tradition, "translation": ms.DEFAULT_TRANSLATION,
            "congregation": congregation, "mode": "feature-conditional", "stage": 0,
            "created": ms.now(), "notes": [], "chat": [],
            "exigency": {"text": "", "sermon": "", "response": ""}}


# ------------------------------------------------------------ engine voice
def stage_questions(s):
    i = s["stage"]
    qs = list(ms.STAGES[i]["questions"])
    if ms.is_black_church(s):
        qs += ms.BLACK_CHURCH_LENSES.get(i, [])
    return qs


def next_question(s):
    qs = stage_questions(s)
    n = sum(1 for x in s["notes"] if x["stage"] == s["stage"])
    if n >= len(qs):
        return "You have been through this stage's questions. Anything left unsaid, or ready for the next stage? (Tap Next stage.)"
    return qs[n]


def opening(s):
    st = ms.STAGES[s["stage"]]
    intro = (f"Come on in. I’m {PERSONA}. I’ve sat through a lot of sermons, and I’m not writing yours. "
             "I’ll ask what the text said, and I won’t let you slide.\n\n") if s["stage"] == 0 and not s["notes"] else ""
    return (f"{intro}{st['name']} (stage {s['stage'] + 1} of {len(ms.STAGES)}). "
            f"Text: {s['text']} ({s['translation']}).\n\n{next_question(s)}")


def engine_reply(s, flags):
    if flags:
        parts = [SASS.get(f["flag"], f["prompt"]) for f in flags]
    else:
        parts = [ACKS[len(s["notes"]) % len(ACKS)]]
    parts.append(next_question(s))
    return "\n\n".join(parts)


# ------------------------------------------------------------ optional LLM
def context_block(s, flags):
    ex = s["exigency"]
    here = [x["text"] for x in s["notes"] if x["stage"] == s["stage"]][-6:]
    return "\n".join([
        "ENGINE RECORD (source of truth; do not contradict it)",
        f"Stage: {ms.STAGES[s['stage']]['name']} ({s['stage'] + 1}/{len(ms.STAGES)})",
        f"Text: {s['text']} | Translation: {s['translation']} | Tradition: {s['tradition']}",
        f"Congregation (preacher's words): {s['congregation'] or 'not given'}",
        f"Text's exigency: {ex['text'] or 'not stated'} | Sermon's exigency: {ex['sermon'] or 'not stated'} | Gospel response: {ex['response'] or 'not stated'}",
        "Preacher's notes at this stage: " + (" || ".join(here) or "none"),
        "Engine flags on the latest note: " + (" | ".join(f["prompt"] for f in flags) or "none"),
        f"Engine's next question: {next_question(s)}",
        PERSONA_RULES,
        "Reply in 2-5 sentences. Fold the flags and the next question in naturally. Ask one question. Never write the sermon.",
    ])


def llm_reply(s, flags):
    msgs = [m for m in s["chat"][-12:]]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    body = json.dumps({"model": MODEL, "max_tokens": 600,
                       "system": SYSTEM + "\n\n" + context_block(s, flags), "messages": msgs}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", [])).strip()


# ------------------------------------------------------------ chat logic
def handle_chat(sid, message):
    s = load(sid)
    if s is None:
        return {"error": "unknown session"}
    msg = message.strip()
    mode = "engine"
    flags = []
    if ms.WRITE_REQUEST_RE.search(msg):
        reply = REFUSAL
    elif msg == "/next":
        ok, m = ms.do_advance(s)
        reply = m + (f"\n\n{opening(s)}" if ok else "")
    elif msg == "/status":
        reply = ms.do_status(s)
    elif msg.startswith(("/exigency ", "/sermon ", "/gospel ")):
        cmd, _, val = msg.partition(" ")
        kw = {"/exigency": "text", "/sermon": "sermon", "/gospel": "response"}[cmd]
        reply = ms.do_exigency(s, **{kw: val.strip()})
    elif msg.startswith("/"):
        reply = "Commands: /next, /status, /exigency <the text's exigency>, /sermon <the sermon's exigency>, /gospel <the fitting response>."
    else:
        _, note = ms.do_note(s, msg)
        flags = note["flags"]
        reply = engine_reply(s, flags)
        if API_KEY:
            s["chat"].append({"role": "user", "content": msg})
            try:
                reply = llm_reply(s, flags) or reply
                mode = "llm+engine"
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                pass
            s["chat"].pop()
    s["chat"] += [{"role": "user", "content": msg}, {"role": "assistant", "content": reply}]
    s["chat"] = s["chat"][-60:]
    save(sid, s)
    return {"reply": reply, "mode": mode, "flags": [f["flag"] for f in flags], **status(s)}


def status(s):
    return {"stage": s["stage"], "stage_name": ms.STAGES[s["stage"]]["name"], "stages": len(ms.STAGES),
            "translation": s["translation"], "persona": PERSONA}


# ------------------------------------------------------------ http
class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype if ctype.startswith("image/") else ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path in ("/", "/index.html"):
            self._send(200, (ROOT / "index.html").read_bytes(), "text/html")
        elif path.startswith("/static/") and path[8:] in ("hero.jpg", "tammy.jpg"):
            f = ROOT / "static" / path[8:]
            self._send(200, f.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=3600"}) if f.exists() else self._json({"error": "not found"}, 404)
        elif path == "/api/export":
            sid = dict(p.split("=", 1) for p in qs.split("&") if "=" in p).get("sid", "")
            s = SID_RE.match(sid) and load(sid)
            if not s:
                return self._json({"error": "unknown session"}, 404)
            self._send(200, ms.do_export(s), "text/markdown",
                       {"Content-Disposition": 'attachment; filename="sermon_record.md"'})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._json({"error": "too large"}, 413)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        if self.path == "/api/start":
            title, text = (d.get("title") or "").strip(), (d.get("text") or "").strip()
            if not title or not text:
                return self._json({"error": "title and text are required"}, 400)
            sid = uuid.uuid4().hex
            s = new_state(title[:120], text[:120], (d.get("denomination") or "")[:60].strip(),
                          (d.get("congregation") or "")[:400].strip())
            first = opening(s)
            s["chat"].append({"role": "assistant", "content": first})
            save(sid, s)
            return self._json({"sid": sid, "reply": first, "mode": "llm+engine" if API_KEY else "engine",
                               "title": s["title"], **status(s)})
        sid = d.get("sid", "")
        if not SID_RE.match(sid) or load(sid) is None:
            return self._json({"error": "unknown session"}, 404)
        if self.path == "/api/chat":
            return self._json(handle_chat(sid, str(d.get("message", ""))[:4000]))
        if self.path == "/api/resume":
            s = load(sid)
            return self._json({"title": s["title"], "chat": s["chat"], "mode": "llm+engine" if API_KEY else "engine",
                               **status(s)})
        self._json({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"Muse Sermon on http://localhost:{port}  (mode: {'LLM + engine' if API_KEY else 'engine only'})")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
