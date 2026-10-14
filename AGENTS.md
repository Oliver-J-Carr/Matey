# AGENTS.md

Guidance for AI coding agents working on Matey. Read this before changing code.

## What Matey is

- A web app demonstrating an agentic home assistant with a pirate persona.
- FastAPI backend running the OpenAI Agents SDK. Vanilla HTML/CSS/JS front end. One container.
- Browser and server talk over a single WebSocket (`/ws`).

## Rules for agents

- Never run `git commit` or `git push`. A human reviews and commits all changes.
- Never read, print or edit `.env`. Use `.env.example` to learn variable names.
- Never hard-code secrets, API keys or tokens.
- Ask before adding, removing or upgrading any dependency (Python or JS/CDN).
- Keep changes focused on the task. No drive-by refactors or reformatting.
- Update `README.md` when user-facing behaviour, setup or env vars change.
- When adding an env var: add it to `app/config.py`, `.env.example` (placeholder value only) and the README table.
- Run `pytest -q` before saying a change is done.
- Ask before making live model calls beyond a quick smoke test. They cost API usage.

## Environment

- Linux shell (macOS and WSL2 also work). Python 3.12+. The container uses `python:3.13-slim`.
- Always use a project virtual environment (`.venv`). Never install packages system-wide.
- Docker with the Compose plugin. Invoke it as `docker compose`, not `docker-compose`.
- The server must bind to `0.0.0.0`, not `127.0.0.1`, or it's unreachable from outside the container.
- The app is served on port 8090. Check the port is free before changing it.
- Agents may have no browser. Verify with tests and `/healthz`, and leave visual UI checks to the human.

## Commands

```bash
# Setup (once, from the repo root)
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

# Tests: no API key or network needed (scripted fake models)
pytest -q

# Build and run (prompts and static files are baked into the image, so rebuild after any change)
docker compose up -d --build --force-recreate

# Check it works
curl -s http://127.0.0.1:8090/healthz      # expect {"ok":true,"version":"..."}
docker logs --tail 50 matey

# Housekeeping: each rebuild leaves an old untagged image behind
docker image prune
```

## Architecture

- `app/main.py`: FastAPI app, static files and the `/ws` WebSocket. One `Conversation` per connection.
- `app/conversation.py`: runs each user message as one traced agent turn.
- `app/brain.py`: brain agent with dynamic instructions (prompt + workspace views).
- `app/voice.py`: voice agent that turns plain messages into Matey's lines.
- `app/tts.py`: optional ElevenLabs text-to-speech that reads those lines aloud. Off when `ELEVENLABS_API_KEY` is blank.
- `app/stt.py`: optional ElevenLabs speech-to-text for the microphone button. Off when `ELEVENLABS_API_KEY` is blank.
- `app/tools.py`: function tools the brain can call.
- `app/hooks.py`: `RunHooks` that feed the activity panel.
- `app/workspace.py`: plain-Python state of the on-screen windows. No AI here.
- `app/context.py`: `MateyContext`, passed to tools and hooks, never sent to the model.
- `app/prompts/*.md`: prompts, loaded once at import time.
- `app/static/`: `index.html`, `style.css`, `app.js` (sockets, windows, feed), `pirate.js` (pixel head).

## Key design decisions (keep these)

- **Replying is a tool.** The brain speaks only by calling `say`. This lets it give progress updates mid-turn and several replies per turn. Its final text output is `done` and is not shown.
- **The persona lives only in the voice step.** The brain writes plain, factual messages. `say` passes them to the voice agent, which adds the pirate. Never add persona, jokes or dialect to the brain prompt, tool docstrings or tool results. The brain knows, as a plain fact, that the user hears it as Matey, and it may ask for a tale or an introduction with a plain instruction ("Tell a short tale about ...", "Introduce yourself as Matey and say you ..."). The voice writes the tale or introduction.
- **The voice sees only the `say` message.** `pirate_line` gets the message plus Matey's earlier lines this turn, never the user's request. Given the whole request, the voice reacted to parts not done yet ("shall I make the list?") and repeated the same hook in every line. The brain makes each message self-contained instead.
- **Different models for different roles.** `BRAIN_MODEL` (planning, tool use) and `VOICE_MODEL` (cheap, fast rewriting) are configured separately. Don't merge them.
- **No persistence in v0.x, by design.** All state is in memory per WebSocket connection. Refreshing the page starts fresh. Don't add a database or file storage unless asked.
- **No user editing of windows in v0.x.** Windows are draggable only. The agent is the only writer.
- **State lives in the backend.** `Workspace` is the source of truth. The browser only renders `ui` events.
- **Two workspace views, not one live snapshot.** The brain sees the workspace frozen at the start of the turn plus a log of changes it made this turn (`changes_this_turn`). A single live snapshot made the model think items it had just added "already existed". Don't revert to a live snapshot.
- **Tracing.** Each user turn is wrapped in `with trace(...)` with `group_id` set to the conversation id. Voice-agent runs nest inside the same trace. Keep this when changing `conversation.py`. `OPENAI_AGENTS_DISABLE_TRACING=true` turns it off.
- **Spoken voice is optional.** With no `ELEVENLABS_API_KEY`, `build_tts()` returns `None` and nothing ElevenLabs-related runs. Every `say` event goes through `MateyContext.deliver_line`, which adds audio when TTS is on and falls back to text only if TTS fails.
- **Voice input is optional too.** With no key, `build_stt()` returns `None`, `hello.transcription` is `null` and the browser hides the mic. A recording is transcribed by `Conversation.handle_voice_message`, then runs through `handle_user_message` like typed text, so the brain never knows the request was spoken.
- **The browser paces speech.** `app.js` queues lines and shows one at a time: until its audio ends, or for a minimum reading time when there is no audio. Audio plays through one shared Web Audio context, woken on Send and kept running while Matey works. A fresh `<audio>` element per line made the first line fade in as the output device woke from idle.
- **Batch list edits.** `add_list_items` and `remove_list_items` take lists, so one call per list, never one per item.
- **No front-end build step.** Plain ES modules, no framework, no bundler. Only external resource: Google Fonts.

## Conventions

- Tool docstrings are sent to the model as tool descriptions. Treat vague docstrings as bugs.
- Tools return errors as `"Error: ..."` strings instead of raising, so the model can recover.
- Every successful state-changing tool must:
  1. change the `Workspace`
  2. push the change with `ctx.context.ui_upsert(...)` or `ui_delete(...)`
  3. return through `_record(ctx, ...)` so it lands in the changes log
- Tool results are plain English and include ids, e.g. `Added to 'Shopping List' (list-1): pears (i3).`
- Never use module-level mutable state. It would be shared across every connected browser.
- Prompts longer than a few lines go in `app/prompts/*.md`. Short inline prompts use implicit string concatenation, not triple-quoted strings (avoids stray indentation).
- Keep `say` calls serialised via `say_lock` so replies arrive in order.
- Version lives in three places, keep them in sync: `app/__init__.py`, `pyproject.toml`, and the image tag in `compose.yaml`.

## Adding a new window type or tool

1. `workspace.py`: add the data and a method. Raise `WorkspaceError` for bad input. Update `snapshot_text()`.
2. `tools.py`: add a `@function_tool` with a precise docstring and follow the three steps under Conventions. Register it in `ALL_TOOLS`.
3. `hooks.py`: add an icon to `_ICONS` and a readable line to `_describe`.
4. `prompts/brain.md`: say when to use the new tool, and when not to.
5. `static/app.js`: add a body renderer to `renderers`. The window shell (`createShell`) is shared, so don't build a new one.
6. `tests/`: add a workspace unit test and a scripted turn in `test_turns.py`.

## WebSocket protocol

- Browser to server:
  - `{"type": "user_message", "text": "..."}`
  - `{"type": "voice_message", "audio": "<base64>", "mime": "audio/webm"}`: a recording from the mic (max 10 MB).
- Server to browser:
  - `hello`: version, model names, `speech` (the TTS label, or `null` when the voice is off) and `transcription` (the STT label, or `null` when voice input is off).
  - `transcript`: `text` heard in a `voice_message`, sent before that turn starts.
  - `status`: `state` of `thinking` or `idle`.
  - `say`: `text` (Matey's line), `plain` (the brain's message) and, when the voice is on, `audio` (base64 MP3).
  - `ui`: `op` of `upsert` (with `component`) or `delete` (with `component_id`).
  - `activity`: feed entries. Tool entries share a `key` (the tool call id) and go from `running` to `done` or `error`.
  - `error`: a short error message.
  - `turn_end`: re-enables the input box.
- Changing an event's shape means updating `app.js` and the tests in the same change.

## Testing

- Tests use the SDK's `agents.testing.ScriptedModel`. Each step scripts the model's tool calls, so no API key is needed.
- `run_turns(brain_steps, voice_lines, messages)` in `tests/test_turns.py` drives full turns and returns events.
- Add a scripted regression test for any agent-behaviour bug you fix in code.
- Prompt quality can't be unit-tested. Describe what to try manually, so a human can check the live app and traces.

## Known pitfalls

- Prompt or static edits do nothing until the image is rebuilt (`--build`). `.env` changes need `--force-recreate`.
- `docker run` fails if a container named `matey` already exists. Use `docker compose`.
- Some models reject `reasoning.effort`. Leave `*_REASONING_EFFORT` blank if a model errors.
- The CSS has `[hidden] { display: none !important; }` because component `display` rules otherwise override the `hidden` attribute.
- `/favicon.ico` needs its explicit route in `main.py`.
- Browsers only allow `getUserMedia` (the mic) on `localhost` or HTTPS. Over plain HTTP from another host, the mic button stays hidden.
- Small models follow prompt constraint language very literally. Phrasing like "rewrite only this line" flattens Matey's personality.
