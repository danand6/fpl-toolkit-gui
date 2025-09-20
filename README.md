# FPL Toolkit

This project now ships with a Python/Flask backend and a React (Vite) frontend so the Toolkit can run in a modern browser UI.

## Backend (Flask)

```bash
python3 backend.py
```

The server exposes JSON endpoints under `/api/*` and proxies player/league features. Ensure you have the required Python dependencies installed beforehand.

## Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server is configured to proxy `/api` calls to `http://localhost:5001`, so make sure the Flask backend is running on that port.

Use `npm run build` for a production bundle (output in `frontend/dist`).

### Frontend dependencies

Running `npm install` pulls in React, Vite, and D3. D3 powers the in-app bar charts and pitch visualisations that accompany the various features (e.g. predicted scorers, differential hunter results, squad layouts, AI predictions).

### Chatbot workflow

Log in with your FPL credentials, then interact with the chat panel. You can type free-form requests ("how will my squad perform next week?", "will I beat Alex?", "any injury risks?", "when should I use my wildcard?") or click one of the suggested prompts. The assistant maps recognised queries onto deterministic FPL features, and falls back to a retrieval-augmented generation pipeline that searches a knowledge base of AI predictions, chip strategy guidance, transfer suggestions, and league projections before crafting an answer. The retrieved context and generated explanation are shown in the main content pane.

If you provide an OpenAI API key via `OPENAI_API_KEY`, the assistant will use `gpt-4o-mini` by default to paraphrase the RAG answer for even better prompt understanding. Set `OPENAI_MODEL` to override.

## Configuration

`config.json.template` documents the structure expected by the backend. The React login form writes actual credentials to `config.json` via the Flask API.
