# Local AI Chatbot

A fully offline, privacy-first AI chatbot for the GNOME desktop. Built with GTK4 + Libadwaita and powered by HuggingFace Transformers, it runs large language models entirely on your own machine — no API keys, no cloud, no telemetry.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![GTK](https://img.shields.io/badge/GTK-4.0-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **ChatGPT-like interface** — sidebar with conversation history, message bubbles, streaming token output
- **Fully local inference** — models run on your CPU or GPU via HuggingFace Transformers
- **Streaming generation** — text appears token by token as it is generated; cancel anytime with the Stop button
- **Markdown rendering** — assistant responses render bold, italic, code blocks, headings, lists, and more
- **Multiple models** — switch models mid-chat from the header dropdown; only one model is kept in memory at a time
- **Automatic model download** — prompted with a confirmation dialog if a selected model is not yet cached locally
- **Per-chat system prompts** — each conversation has its own editable system prompt
- **Persistent chat history** — all conversations are saved as JSON files and reload between sessions
- **Auto-titled chats** — conversation titles are generated from the first user message
- **Rename & delete chats** — via the context menu in the sidebar
- **Copy button** — on every message bubble
- **Search** — filter conversations in the sidebar by title
- **Light/dark theme** — follows the system setting automatically

---

## Requirements

### System packages

**GTK4 + Libadwaita** (usually pre-installed on GNOME):

```bash
# Debian / Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gtksource-5

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita gtksourceview5

# Arch
sudo pacman -S python-gobject gtk4 libadwaita gtksourceview5
```

### Python packages

```bash
pip install -r requirements.txt
```

`requirements.txt` includes:
- `PyGObject` — GTK4 Python bindings
- `transformers` — HuggingFace model loading and inference
- `torch` — PyTorch backend
- `huggingface_hub` — model downloading and cache management
- `accelerate` — automatic device mapping (CPU/GPU)
- `mistune` — markdown parsing (used for response rendering)

> **GPU acceleration**: if you have an NVIDIA GPU, install the CUDA-enabled PyTorch build from [pytorch.org](https://pytorch.org/get-started/locally/) before running `pip install -r requirements.txt`. The app will automatically use the GPU via `device_map="auto"`.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourname/local-ai-chatbot.git
cd local-ai-chatbot

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Run the app
python main.py
```

---

## Project structure

```
local-ai-chatbot/
├── main.py               # Entry point — creates and runs the Adw.Application
├── models.json           # List of available models (name, HuggingFace ID, description)
├── requirements.txt
├── README.md
└── app/
    ├── __init__.py
    ├── window.py         # Main window — wires all components together
    ├── sidebar.py        # Conversation list, search, rename, delete
    ├── chat_view.py      # Message bubbles, markdown rendering, input bar
    ├── model_manager.py  # Model config, cache detection, download, load/unload
    ├── inference.py      # Streaming inference via TextIteratorStreamer
    ├── chat_store.py     # JSON read/write for conversations
    └── settings.py       # Persistent app settings (default system prompt, etc.)
```

---

## Adding models

Edit `models.json` in the project root to add any HuggingFace causal-language model:

```json
{
  "models": [
    {
      "name": "My Model",
      "hf_id": "organisation/model-name",
      "description": "Short description shown in the download dialog"
    }
  ]
}
```

The app will prompt you to download the model the first time you select it. Models are stored in the standard HuggingFace cache (`~/.cache/huggingface/hub/`).

### Included model presets

| Name       | HuggingFace ID        | Approx. size | Notes                    |
|------------|-----------------------|--------------|--------------------------|
| Qwen3 0.6B | `Qwen/Qwen3-0.6B`     | ~400 MB      | Fastest, minimal RAM     |
| Qwen3 1.7B | `Qwen/Qwen3-1.7B`     | ~1.1 GB      | Good for quick tasks     |
| Qwen3 4B   | `Qwen/Qwen3-4B`       | ~2.5 GB      | Recommended starting point |
| Qwen3 8B   | `Qwen/Qwen3-8B`       | ~5 GB        | Balanced quality/speed   |
| Qwen3 14B  | `Qwen/Qwen3-14B`      | ~9 GB        | High quality, needs 16 GB RAM |

---

## Data locations

| Data | Location |
|------|----------|
| Conversations | `~/.local/share/localai/chats/` |
| Settings | `~/.config/localai/settings.json` |
| Model cache | `~/.cache/huggingface/hub/` |

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift+Enter` | Insert newline in input |

---

## Troubleshooting

**The app starts but the model won't load**
Make sure `torch` is installed and that you have enough RAM for the selected model. Try a smaller model first (Qwen3 0.6B or 1.7B).

**Generation never produces output / stays on "Stop"**
This is usually a tokenizer `apply_chat_template` issue. Ensure `transformers >= 4.40.0` is installed (`pip install -U transformers`).

**Text appears but markdown isn't rendering**
Make sure `mistune >= 3.0.0` is installed: `pip install -U mistune`.

**Download hangs or fails**
Check your internet connection. The HuggingFace hub download goes to `~/.cache/huggingface/hub/`. You can also manually download a model with:
```bash
huggingface-cli download Qwen/Qwen3-4B
```

---

## License

MIT — see `LICENSE` for details.

## TO DO
- Schermata di impostazioni avanzate per controllare temperatura e altri parametri