# API Change Guard

Compare two OpenAPI YAML files, detect a focused set of compatibility changes,
and use a local Ollama model to produce a Pydantic-validated risk report.

The first version detects added/removed endpoints, added/removed fields,
changed field types, newly required fields, and removed inline response
properties. It intentionally does not send either complete API document to
Ollama; only the deterministic change list is sent.

## Install

From PowerShell, run:

```powershell
cd D:\PYTHONPROJECT\AIProject\api-change-guard
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

If `.venv` does not exist yet, create it from the project folder first:

```powershell
python -m venv .venv
```

Install the Ollama desktop application separately, start it, and download a
model. For example:

```powershell
ollama pull qwen3:4b
```

To use another model, set `OLLAMA_MODEL` in the terminal before starting the
API, for example `$env:OLLAMA_MODEL = "llama3.2"`.

## Run

From PowerShell, run the launcher from the project root:

cd D:\PYTHONPROJECT\AIProject\api-change-guard
.\run.bat
```

Or, even if the terminal is currently in `.venv\Scripts`, launch it by its
absolute path:

```powershell
& "D:\PYTHONPROJECT\AIProject\api-change-guard\run.bat"
```

The launcher creates `.venv` if needed, installs project dependencies if
they're missing, starts FastAPI in a separate terminal window, and runs
Streamlit in the current terminal. It does not require activating `.venv` or
changing PowerShell's script execution policy. Close the API window to stop
the backend.

The API is available at `http://127.0.0.1:8000`; its interactive docs are at
`http://127.0.0.1:8000/docs`. Streamlit prints the dashboard URL, usually
`http://localhost:8501`.

Upload the two example files from `examples/` and click **Analyze changes**.
Ollama must be running and have the configured model downloaded when there are
changes to assess. The API returns a clear `503` error if Ollama is unavailable.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```
