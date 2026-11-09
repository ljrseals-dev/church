# Muse Sermon by Rihanna

A study companion for preachers in the African American church tradition, King James Version by default, in the same pattern as Muse Engine: stdlib-only
Python, plain JSON on disk, no network. It does not write the sermon. It records
your notes, tracks where preparation sits, and asks the questions the work requires.

## Built for the Black church pulpit
Defaults: tradition = Black church (African American), translation = KJV. At every stage it adds questions drawn from that tradition: the cloud of witnesses, whose cry or sin the text names, the concrete conditions your people face, hope vs. denial, the refrain, humor and the close, stewardship plus structure. It does not guess your denomination's distinctives; you name them. For KJV it reminds you to check archaic or shifted wording against the Hebrew/Greek.

## Stages
The Text, Exegesis, The Text's Exigency, The Hearers, The Canon and Christ,
The Fitting Response, Pastoral Check.

## Use
    python3 muse_sermon.py init --dir ./hold_fast --title "Hold Fast" --text "Hebrews 4:12-16" 
    python3 muse_sermon.py note --dir ./hold_fast "The word 'rest' keeps returning in 4:9-11"
    python3 muse_sermon.py consult --dir ./hold_fast
    python3 muse_sermon.py exigency --dir ./hold_fast --text "..." --sermon "..." --response "..."
    python3 muse_sermon.py advance --dir ./hold_fast
    python3 muse_sermon.py export --dir ./hold_fast --out record.md
    python3 muse_sermon.py chat --dir ./hold_fast      # interactive
    python3 muse_sermon.py selftest                    # calibration run

## What it flags
- Cheap inspiration and cheap despair / totalizing
- Your agenda showing up where the text should be
- Overconfident readings ("obviously", "clearly")
- Application arriving before the text's exigency has been heard
- Exegesis notes with no verse reference
- Leaving the Exigency stage without a stated text exigency (override with --force)

## Modes
Every output declares its mode. `selftest` is calibration (fixed fixtures; proves
the pipeline). Everything else is feature-conditional (responds to your notes).
A calibration pass is never a pastoral result.

## With an LLM
SYSTEM_PROMPT.md is the matching prompt. The engine's record is the source of
truth; the LLM only renders questions. Add your own tradition's distinctives to
TRADITION_PROMPTS in muse_sermon.py; the engine does not guess them.

MIT license.
