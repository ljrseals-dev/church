#!/usr/bin/env python3
"""Muse Sermon -- a study companion for preachers. Stdlib only, Python 3.9+.

It does not write the sermon. It records the preacher's own notes, tracks
where the preparation sits, and asks the questions the work requires.

Every output carries a mode declaration:
  feature-conditional : questions and flags respond to what the preacher wrote
  calibration         : fixed fixtures; proves the pipeline works (selftest)
"""
import argparse
import datetime
import json
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------- stages
STAGES = [
    {
        "name": "The Text",
        "questions": [
            "What have you noticed in this text? (Before any commentary.)",
            "What genre is it, and what comes immediately before and after?",
            "What surprised you, or bothered you?",
        ],
        "warnings": ["Do not reach for a theme yet. Look at the text first."],
    },
    {
        "name": "Exegesis",
        "questions": [
            "Who wrote this, to whom, and why? What is the historical situation?",
            "Which key words carry weight in the original language, and what is their range of meaning?",
            "What theological claims does the text itself make?",
            "What does the text NOT say?",
        ],
        "warnings": [
            "Name which translation you are quoting.",
            "Where commentators disagree, name the disagreement instead of picking silently.",
        ],
    },
    {
        "name": "The Text's Exigency",
        "questions": [
            "If this text could speak, what would it say is wrong?",
            "What defect or obstacle does it name? What is 'other than it should be'?",
            "Is that the text's claim, or the claim you came wanting it to make?",
            "Is there a 'now' to this text -- what does it say is urgent?",
        ],
        "warnings": [
            "Exigency is not application. Application comes after the text has been heard.",
            "Hear it, don't manufacture it. A text's exigency can be ignored or suppressed.",
        ],
    },
    {
        "name": "The Hearers",
        "questions": [
            "Who is in the room? (the grieving, the doubting, the new believer, the long-time member, the visitor)",
            "What will this text do to them?",
            "Where does the sermon need to be gentle, and where direct?",
            "Does the text's exigency match the congregation's felt need? If not, how do you preach it anyway?",
        ],
        "warnings": [
            "Stott's double obligation: no phony relevance, no phony faithfulness.",
            "You know this congregation; this tool does not.",
        ],
    },
    {
        "name": "The Canon and Christ",
        "questions": [
            "Where does this text sit in the larger biblical narrative?",
            "How does its exigency relate to the person and work of Christ?",
            "What does your tradition say about how to read this kind of text?",
        ],
        "warnings": [
            "Do not leave Christ out because the text is judgment or sanctification.",
            "Do not force Christ in by skipping what the text itself says.",
        ],
    },
    {
        "name": "The Fitting Response",
        "questions": [
            "In one sentence: what is the fitting response to the exigency (the Gospel)?",
            "What structure serves this text -- running the text, text interrupted, text delayed, scene change?",
            "Is there a refrain that keeps the text's claim present?",
            "Where is the moment the claim lands with urgency? What happens after it?",
        ],
        "warnings": ["A sermon that names the exigency but offers no fitting response has failed."],
    },
    {
        "name": "Pastoral Check",
        "questions": [
            "Read your own first and last sentences. Do they move from exigency to response?",
            "Could this sermon be preached without the text? If so, what was dropped?",
            "What would you cut if you had five fewer minutes?",
        ],
        "warnings": ["The sermon must be yours. Nothing here is a draft."],
    },
]

# Muse Sermon is built for the African American preaching tradition and
# defaults to it. Lenses below are questions drawn from the module material
# (Exigency of Text, Wit and Humor, Financial Prosperity, Current Events,
# History and Theology). They are questions, never answers.
DEFAULT_TRADITION = "Black church (African American)"
DEFAULT_TRANSLATION = "KJV"

BLACK_CHURCH_LENSES = {
    0: ["Who in your own cloud of witnesses (elders, mothers of the church, the preachers who raised you) has stood on this text before you?",
        "Whose voice does the text give? The oppressed, the oppressor, the bystander?"],
    1: ["Who were the original hearers, and what pressure were they under? Were they a people under occupation, in exile, in bondage?",
        "Whose side does the text take? Show it from the verses, not from your convictions."],
    2: ["Does the text name the cry of the afflicted, the sin of the powerful, or both? Which defect is 'other than it should be'?",
        "Does the text carry the liberating claim you want, or are you importing it? Say where."],
    3: ["What are the concrete conditions your people face this week (work, health coverage, the vote, housing, the water)? Name them specifically; no generalities, no totalizing.",
        "How does your congregation's history of survival and trauma change the urgency this text carries?",
        "Is the word you are preparing hope, or denial? How does your tradition tell them apart?"],
    4: ["Where does the text meet suffering, and where does Christ stand with the afflicted in it? Does the text itself bear that reading?",
        "If the text touches money, can you hold biblical stewardship and the structural reality together, without 'just budget better' or 'the system is rigged, don't try'?"],
    5: ["Where does the refrain return to bring the people back to the text?",
        "Where does humor release the tension before the climactic close, and is it earned by the text rather than decorating it?",
        "Does the close equip as well as comfort?"],
    6: ["Is anything here cheap inspiration ('they did it, so can we') or cheap despair ('it's worse than ever')? What did the ancestors get right, and what did they miss?",
        "Would your mother of the church hear the text in this sermon?"],
}

KJV_CAUTION = ("KJV (1611) wording: check archaic or shifted English words against the Hebrew/Greek "
               "before building on them. Do not rest a point on an English word the original does not carry.")


def is_black_church(state):
    t = (state.get("tradition") or "").lower()
    return "black" in t or "african" in t


# ---------------------------------------------------------------- flags
FLAG_RULES = [
    ("agenda", r"\b(the point is|my point|i want to (say|tell|preach)|the sermon is about|the theme is|i need to (say|tell))\b",
     "That sounds like your agenda. Where, in the text, is it said? Point to the verse."),
    ("certainty", r"\b(obviously|clearly|everyone knows|of course the text)\b",
     "Name your reasoning: 'This reading depends on...' Is there a faithful reading that disagrees?"),
    ("cheap_inspiration", r"\b(they did it,? so (can|could) we|the ancestors did it)\b",
     "Cheap inspiration? What did the ancestors get right, and what did they miss? Be specific."),
    ("cheap_despair", r"\b(nothing (has )?changed|it'?s (all )?worse than ever|same as slavery)\b",
     "Totalizing? Name the specific condition and the specific precedent without collapsing one into the other."),
    ("application_early", r"\b(apply|application|relevant|relevance|today'?s world)\b",
     "Application before exigency? Hold it until the text has been heard."),
]
REF_RE = re.compile(r"\b\d{1,3}:\d{1,3}\b")
WRITE_REQUEST_RE = re.compile(
    r"\b(write|draft|generate|compose)\b.{0,25}\b(sermon|homily|message)\b", re.I)
REFUSAL = ("I can help you think through the structure, the exegesis, and the pastoral "
           "application, but the sermon has to be yours. What part of it are you stuck on?")

STOP = set("the a an and or but of to in on for with is are was were be that this it as at by from "
           "we you i they he she not no what who how why when where which will would can could".split())


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def mode_header(state, mode=None):
    return (f"MODE: {mode or state.get('mode', 'feature-conditional')}\n"
            f"MODULE: 5 (Sermon Chatbot) + 4 (Exigency of Text)\n"
            f"MEDIUM: sermon preparation (study companion; not a draft)\n"
            f"TRANSLATION: {state.get('translation', DEFAULT_TRANSLATION)}\n")


# ---------------------------------------------------------------- storage
def path_for(d):
    return Path(d) / "sermon.json"


def load(d):
    p = path_for(d)
    if not p.exists():
        sys.exit(f"No sermon found in {d}. Run: muse_sermon.py init --dir {d} --title ... --text ...")
    return json.loads(p.read_text(encoding="utf-8"))


def save(d, state):
    path_for(d).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- logic
def analyze(note, stage_idx):
    flags = []
    for key, pattern, msg in FLAG_RULES:
        if key == "application_early" and stage_idx > 2:
            continue
        if re.search(pattern, note, re.I):
            flags.append({"flag": key, "prompt": msg})
    if stage_idx in (1, 2) and not REF_RE.search(note):
        flags.append({"flag": "no_anchor", "prompt": "Which verse is this resting on? (e.g. 4:12)"})
    return flags


def tokens(s):
    return {w for w in re.findall(r"[a-z']+", s.lower()) if w not in STOP and len(w) > 2}


def overlap(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return None
    return round(len(ta & tb) / len(ta | tb), 2)


def tradition_prompt(state):
    t = (state.get("tradition") or "").strip().lower()
    if is_black_church(state):
        return ("You are in the African American preaching tradition. Name your own church's distinctives "
                "(denomination, liturgy, call and response); Muse Sermon will not guess them.")
    if "lutheran" in t:
        return "Law/Gospel: where does the text name the defect (Law) and where does it declare the remedy (Gospel)?"
    return ("Name your tradition's distinctives for reading this kind of text. "
            "Muse Sermon will not guess them for you.")


def do_consult(state):
    i = state["stage"]
    st = STAGES[i]
    out = [mode_header(state), f"# Consult: {st['name']}  (stage {i + 1} of {len(STAGES)})",
           f"Text: {state['text']} ({state.get('translation', DEFAULT_TRANSLATION)})"]
    if state.get("congregation"):
        out.append(f"Congregation (your words): {state['congregation']}")
    out += ["", "## Questions", *[f"- {q}" for q in st["questions"]],
            "", "## Cautions", *[f"- {w}" for w in st["warnings"]],
            "", "## Your tradition", f"- {tradition_prompt(state)}"]
    if is_black_church(state):
        out += ["", "## Through the Black church tradition", *[f"- {q}" for q in BLACK_CHURCH_LENSES.get(i, [])]]
    if state.get("translation", DEFAULT_TRANSLATION).upper() == "KJV" and i in (0, 1, 2):
        out += ["", "## Translation", f"- {KJV_CAUTION}"]
    last = [n for n in state["notes"] if n["stage"] == i]
    if last:
        out += ["", "## Based on your last note", f"> {last[-1]['text']}"]
        if last[-1]["flags"]:
            out += [f"- {f['prompt']}" for f in last[-1]["flags"]]
        else:
            out.append("- Nothing flagged. What does that note leave unsaid?")
    return "\n".join(out)


def do_note(state, text):
    if WRITE_REQUEST_RE.search(text):
        return REFUSAL, None
    i = state["stage"]
    note = {"stage": i, "stage_name": STAGES[i]["name"], "time": now(),
            "text": text, "flags": analyze(text, i)}
    state["notes"].append(note)
    lines = [f"Recorded at: {note['stage_name']}", f"> {text}"]
    lines += [f"- {f['prompt']}" for f in note["flags"]]
    return "\n".join(lines), note


def do_exigency(state, text=None, sermon=None, response=None):
    ex = state["exigency"]
    for k, v in (("text", text), ("sermon", sermon), ("response", response)):
        if v:
            ex[k] = v
    out = ["## Exigency record",
           f"- The text's exigency: {ex['text'] or '(not yet stated)'}",
           f"- The sermon's exigency: {ex['sermon'] or '(not yet stated)'}",
           f"- The fitting response (Gospel): {ex['response'] or '(not yet stated)'}"]
    if ex["text"] and ex["sermon"]:
        o = overlap(ex["text"], ex["sermon"])
        out.append(f"- Word overlap, text vs. sermon: {o}  (a rough signal, not a verdict)")
        out.append("- Question: are these the same claim in different words, or two different claims? "
                   "If different, which one does the text make?")
    return "\n".join(out)


def do_advance(state, force=False):
    i = state["stage"]
    if i == 2 and not state["exigency"]["text"] and not force:
        return False, ("You are leaving the Exigency stage without a statement of the text's exigency. "
                       "Set one with `exigency --text \"...\"`, or advance with --force.")
    if i >= len(STAGES) - 1:
        return False, "Already at the last stage."
    state["stage"] += 1
    return True, f"Advanced to: {STAGES[state['stage']]['name']}"


def do_status(state):
    i = state["stage"]
    lines = [mode_header(state), f"# {state['title']}", f"Text: {state['text']}",
             f"Tradition: {state.get('tradition') or '(not named)'}", ""]
    for n, st in enumerate(STAGES):
        mark = ">>" if n == i else ("ok" if n < i else "  ")
        count = sum(1 for x in state["notes"] if x["stage"] == n)
        lines.append(f"{mark} {n + 1}. {st['name']}  ({count} notes)")
    return "\n".join(lines)


def do_export(state):
    ex = state["exigency"]
    out = [mode_header(state), f"# {state['title']} -- preparation record", "",
           "## 1. Structured object", "```json",
           json.dumps({k: state[k] for k in ("title", "text", "translation", "tradition", "congregation", "stage", "exigency")},
                      indent=2, ensure_ascii=False), "```", "",
           "## 2. Text vs. preacher map",
           "| | Statement |", "|---|---|",
           f"| Text's exigency | {ex['text'] or '-'} |",
           f"| Sermon's exigency | {ex['sermon'] or '-'} |",
           f"| Fitting response | {ex['response'] or '-'} |", "",
           "## 3. Working record (your words only)"]
    for n, st in enumerate(STAGES):
        notes = [x for x in state["notes"] if x["stage"] == n]
        if notes:
            out += ["", f"### {st['name']}"]
            for x in notes:
                out.append(f"- {x['text']}")
                out += [f"  - (open question) {f['prompt']}" for f in x["flags"]]
    out += ["", "_This is a study record, not a sermon. The sermon has to be yours._"]
    return "\n".join(out)


# ---------------------------------------------------------------- commands
def cmd_init(a):
    p = Path(a.dir)
    p.mkdir(parents=True, exist_ok=True)
    state = {"title": a.title, "text": a.text, "tradition": a.tradition or DEFAULT_TRADITION,
             "translation": a.translation or DEFAULT_TRANSLATION,
             "congregation": a.congregation or "", "mode": "feature-conditional",
             "stage": 0, "created": now(), "notes": [],
             "exigency": {"text": "", "sermon": "", "response": ""}}
    save(a.dir, state)
    print(f"Initialized: {a.title} ({a.text})\n")
    print(do_consult(state))


def cmd_note(a):
    s = load(a.dir)
    msg, _ = do_note(s, a.note)
    save(a.dir, s)
    print(msg)


def cmd_consult(a):
    print(do_consult(load(a.dir)))


def cmd_exigency(a):
    s = load(a.dir)
    print(do_exigency(s, a.text, a.sermon, a.response))
    save(a.dir, s)


def cmd_advance(a):
    s = load(a.dir)
    ok, msg = do_advance(s, a.force)
    if ok:
        save(a.dir, s)
    print(msg)


def cmd_status(a):
    print(do_status(load(a.dir)))


def cmd_export(a):
    md = do_export(load(a.dir))
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Wrote {a.out}")
    else:
        print(md)


def cmd_draft(a):
    print(REFUSAL)


def cmd_chat(a):
    s = load(a.dir)
    print(do_consult(s))
    print("\nType your notes. Commands: /next /status /consult /exigency /export /quit\n")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "/quit":
            break
        elif line == "/next":
            print(do_advance(s)[1])
        elif line == "/status":
            print(do_status(s))
        elif line == "/consult":
            print(do_consult(s))
        elif line == "/export":
            print(do_export(s))
        elif line.startswith("/exigency"):
            print(do_exigency(s, text=line[9:].strip() or None))
        else:
            print(do_note(s, line)[0])
        save(a.dir, s)


def cmd_selftest(a):
    """Calibration mode: fixed fixtures; proves the pipeline works."""
    with tempfile.TemporaryDirectory() as d:
        ns = argparse.Namespace(dir=d, title="Fixture", text="Fixture 1:1", tradition=None, translation=None, congregation="")
        cmd_init(ns)
        s = load(d)
        assert "agenda" in [f["flag"] for f in do_note(s, "The point is that we should all give more.")[1]["flags"]]
        assert do_note(s, "Please write me a sermon on this")[1] is None
        s["stage"] = 2
        assert not do_advance(s)[0]
        s["exigency"]["text"] = "the people have forgotten the covenant"
        assert do_advance(s)[0]
        assert overlap("the people forgot the covenant", "the people forgot the covenant") == 1.0
        assert s["translation"] == "KJV" and is_black_church(s)
        assert "Black church" in do_consult(s)
        assert "cheap_inspiration" in [f["flag"] for f in do_note(s, "They did it, so can we")[1]["flags"]]
        save(d, s)
        assert "## 3. Working record" in do_export(load(d))
    print("\nMODE: calibration -- selftest passed. This proves the pipeline works; "
          "it is not a pastoral result.")


def main():
    ap = argparse.ArgumentParser(description="Muse Sermon -- a study companion for preachers.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, help=kw.pop("help", None))
        if name not in ("draft", "selftest"):
            p.add_argument("--dir", default=".", help="sermon directory")
        p.set_defaults(fn=fn)
        return p

    p = add("init", cmd_init, help="start a sermon")
    p.add_argument("--title", required=True)
    p.add_argument("--text", required=True, help='passage, e.g. "Hebrews 4:12-16"')
    p.add_argument("--tradition", help="default: Black church (African American)")
    p.add_argument("--translation", help="default: KJV")
    p.add_argument("--congregation", help="your own description of who is in the room")
    p = add("note", cmd_note, help="record a note at the current stage")
    p.add_argument("note")
    add("consult", cmd_consult, help="questions and cautions for this stage")
    p = add("exigency", cmd_exigency, help="record/compare exigency statements")
    p.add_argument("--text")
    p.add_argument("--sermon")
    p.add_argument("--response")
    p = add("advance", cmd_advance, help="next stage")
    p.add_argument("--force", action="store_true")
    add("status", cmd_status)
    p = add("export", cmd_export, help="export the study record as markdown")
    p.add_argument("--out")
    add("chat", cmd_chat, help="interactive session")
    add("draft", cmd_draft, help="(declined) write the sermon")
    add("selftest", cmd_selftest, help="calibration run")
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
