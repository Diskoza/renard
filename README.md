# Renard — a local AI assistant for your Windows PC

Renard is a personal desktop assistant that runs **entirely on your own computer**. The language model runs in
[Ollama](https://ollama.com), speech recognition and synthesis run locally, and no account, API key or subscription is
needed. It talks, controls programs, works with files, photos and documents, and keeps a memory of you — all offline.

> **Language:** the interface, the prompts and the voice are **Russian** (with Polish, Ukrainian and English for speech
> recognition and some voices). The code and this README are in English; translating the UI is a welcome contribution.

## Highlights

- **Fully local.** One LLM in video memory at a time; simple commands («громче», «открой Steam», «какая погода») are
  handled by a rule-based router in under a second without the model at all.
- **Three effort modes.** `low` / `medium` for chat, commands, files and small code (gemma4 12B or e4b), `high` for
  harder multi-step work (qwen3.6 35B-A3B). The mode is picked automatically or set by hand.
- **Many interfaces, one server.** Desktop window with a tray icon (`Ctrl+Alt+Space`), a web UI, a terminal UI
  (`pc`, inspired by Claude Code) and a Telegram bot — all clients of the same background server, sharing memory and
  history.
- **Voice.** Wake word (Vosk, CPU only, ~0% CPU in silence), faster-whisper on the GPU, Piper TTS, barge-in, follow-up
  questions without the wake word. Your own voice: clone one from a 10-second sample, or «bake» a full Piper voice
  from a longer recording (vocal separation, automatic filtering, fine-tuning on your GPU).
- **Controls the PC.** Starts and closes any installed program, windows and monitors, volume per app, media keys,
  power, processes, drivers, installs from winget, Wake-on-LAN. An **app operator** drives any program through Windows UI
  Automation step by step and remembers what worked; risky steps (send, delete, buy, publish) always wait for your «да».
- **Files and documents.** Search by name and content, project maps, recent files, safe edits, delete only to the
  Recycle Bin. Reads PDF / Word / Excel / PowerPoint, makes documents and converts between formats.
- **Photos.** Gentle «make it pretty» retouch (noise, local contrast, shadows, glare, warmth, faces), best-of-a-series
  picking, face-aware Instagram / Stories crops, background removal, upscaling, collages and memes. Optional AI repaint of
  a painted area (Stable Diffusion XL inpainting) in a separate environment, always after confirmation.
- **Internet without a browser.** Web search with sources, ~100 site readers (YouTube, GitHub, Wikipedia, Reddit, Steam…),
  weather, news, currency. A separate Chrome profile for sites you sign in to yourself.
- **Messengers.** Reads and sends Telegram / Discord messages through the desktop apps (text exactly as you said it,
  always confirmed). Mail over IMAP.
- **Planner.** Tasks, notes, calendar, reminders and scheduled jobs, a morning summary.
- **Commands builder.** Phrase / hotkey / schedule → a chain of blocks (open, type, click, wait, HTTP, AI step…),
  a gallery of ready automations, and «remember what we just did as a command».
- **Code.** Writes and runs Python / Node in a sandbox with a whitelist and time limits, reads the error, fixes it.
  Can hand bigger jobs to coding agents you have installed (Claude Code, Codex, Gemini CLI, aider).
- **Skills, plugins, MCP.** Skills in the agentskills.io format (`skills/`), plugins (`plugins/`), and any MCP server
  as a connector.
- **Memory.** Notes about you in Markdown, the whole history in SQLite with search, a background pass that files what
  you said about yourself, corrections you make are learned.
- **Companion.** A 3D VRM avatar (or a 2D picture, a .glb robot, or a pixel chibi) that lives on the desktop, walks on
  the taskbar, sits on windows, reacts to the weather and to what the assistant is doing. Personas with their own name,
  voice, wake word and look.
- **Study mode.** Careful tutor answers with checked calculations and Wikipedia.
- **Plays nice with games.** Heavy jobs pause and models leave video memory while a game is in the foreground.

## Requirements

| | |
|---|---|
| OS | Windows 10 / 11 (64-bit) |
| Python | 3.11 |
| LLM runtime | [Ollama](https://ollama.com) |
| GPU | NVIDIA with 8–12 GB VRAM recommended (works slower with less; CPU-only is possible but slow) |
| RAM | 16 GB, 32 GB for the `high` mode |
| Optional | Node.js (MCP connectors, some tools), ffmpeg (radio, media), Chrome (sites with sign-in) |

## Quick start

```bat
git clone <this repository> renard
cd renard
setup.cmd                      :: venv + Python packages (one time)
ollama pull gemma4:12b         :: the default model for low / medium / study
ollama pull qwen3.6:35b-a3b    :: optional, the «high» mode
run.cmd                        :: server + web UI at http://127.0.0.1:8790
```

Then, optionally:

```bat
install_shortcuts.cmd          :: desktop / Start menu shortcuts and the `pc` command
pc-window.cmd                  :: desktop window + tray icon (Ctrl+Alt+Space shows / hides it)
pc                             :: terminal UI
```

Speech models (Whisper, Piper voices, Vosk) are downloaded on first use into `data/models`.

### Optional: AI repaint of photos

`photo_ai` runs Stable Diffusion XL inpainting from its own virtual environment so the main one stays small:

```bat
py -3.11 -m venv %USERPROFILE%\photo-ai\venv
%USERPROFILE%\photo-ai\venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu124
%USERPROFILE%\photo-ai\venv\Scripts\pip install diffusers transformers accelerate opencv-python pillow
```

The model (`diffusers/stable-diffusion-xl-1.0-inpainting-0.1`, ~7 GB) is downloaded on the first run.

## Configuration

| File | What |
|---|---|
| `config/settings.json` | models of each mode, folders the assistant may touch (`files.allowed_roots`), monitoring thresholds, voice, home city, school pages |
| `config/apps.json` | your own program aliases (everything else is found automatically) |
| `config/radio.json` | radio stations |
| `data/` | everything personal: memory, history, prefs, voices, avatars, tokens — created on first run, never committed |

Most settings are also in the UI (**Настройки**, **ИИ**, **Голос**, **Модель**). Service tokens (Telegram bot, mail,
connectors) are stored only in `data/` and are entered in the UI.

**Telegram bot:** create a bot with @BotFather, paste the token in **Настройки → Telegram**, then send the pairing code
from the UI to the bot. Only paired accounts are answered.

## How it works

```
 desktop window ─┐
 web UI ─────────┤                ┌─ router (rules, no LLM) ──► tools
 terminal UI ────┼──► server ─────┤
 Telegram bot ───┤   (FastAPI)    └─ agent loop (Ollama) ─────► tools ──► confirmation for risky steps
 voice / wake ───┘        │
                          └─ memory (SQLite + Markdown), planner, monitor, companion events
```

- `agent/main.py` — the server (HTTP + WebSocket on `127.0.0.1:8790`), started by every interface.
- `agent/core.py` — the agent loop: prompt, tool choice (`agent/toolpick.py` gives the model only the tools a request
  needs), steps, confirmations, honesty checks.
- `agent/router.py` — instant answers for common commands without the LLM.
- `agent/llm.py` — Ollama client; one model in VRAM, warm-up while you are at the PC, unload while you play.
- `agent/tools/` — the tools (one module per area); `agent/app_operator.py` — the UI-automation operator.
- `agent/voice.py`, `agent/wake.py` — speech in / out, wake word; `agent/voicebake.py` — training your own voice.
- `web/` — the UI (plain ES modules, three.js + three-vrm for the avatar).
- `skills/`, `plugins/` — built-in skills and the developer plugin.
- `waker/` — a tiny Wake-on-LAN helper for an always-on device.

## Safety

- File access only inside `files.allowed_roots` and the workspace; deleting goes to the Recycle Bin.
- Sending messages, deleting, installing, power actions, scripts that change the PC, publishing — always ask first,
  even in the automatic permission mode.
- Text from web pages, chats and windows is treated as data, never as instructions.
- The server listens on `127.0.0.1` only and rejects WebSocket connections from other origins.

## Third-party code and models

- [three.js](https://threejs.org) and [three-vrm](https://github.com/pixiv/three-vrm) (MIT), [KaTeX](https://katex.org)
  (MIT), [Drawflow](https://github.com/jerosoler/Drawflow) (MIT) — bundled in `web/vendor/`, see
  [THIRD_PARTY.md](THIRD_PARTY.md).
- Models downloaded at run time keep their own licenses: Ollama models, faster-whisper / Whisper, Piper voices, Vosk,
  OmniVoice, Stable Diffusion XL inpainting (CreativeML Open RAIL++-M). Check them before redistributing.
- Use voice cloning only with the consent of the person whose voice it is.

## License

[GNU General Public License v3.0](LICENSE). You may use, study, change and share this software; if you distribute a
modified version, you must publish its source code under the same license.
