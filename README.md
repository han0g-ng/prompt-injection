# Prompt Injection Defense Demo (University Thesis)

This project demonstrates:
- A vulnerable LLM chatbot that can be attacked with prompt injection.
- Automated red-teaming evaluation using PyRIT.
- Fine-tuning an SLM guard model (Llama Prompt Guard 86M).
- A secured chatbot using middleware to block injection before prompts reach the core LLM.
- A modern web UI to visually showcase attack vs defense.

## Project Structure

```text
project_root/
├── data/
├── models/
├── src/
│   ├── api/
│   │   ├── vulnerable_app.py
│   │   └── secure_app.py
│   ├── frontend/
│   │   ├── index.html
│   │   ├── style.css
│   │   └── script.js
│   └── training/
│       └── train_guard.py
├── eval/
│   ├── attack_vulnerable.py
│   └── attack_secure.py
├── requirements.txt
└── README.md
```

## 1. Setup (Local)

1. Create and activate virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Set OpenAI API key for vulnerable app:

```powershell
$env:OPENAI_API_KEY="your_openai_api_key"
```

4. Run preflight check (recommended):

```powershell
python src\api\preflight_check.py
```

## 2. Milestone 1: Vulnerable App + Web UI

Run vulnerable backend:

```powershell
python src\api\vulnerable_app.py
```

Optional model override:

```powershell
$env:OPENAI_MODEL="gpt-4o-mini"
```

Open UI:
- http://localhost:8000

API endpoint:
- POST http://localhost:8000/api/chat
- Body: `{ "message": "..." }`

## 3. Milestone 2: Baseline PyRIT Evaluation

In a new terminal (while vulnerable app is running):

```powershell
python eval\attack_vulnerable.py
```

Expected:
- Script prints baseline ASR.
- PyRIT memory SQLite is stored under `data/pyrit_memory.db`.

## 4. Milestone 3: Train Prompt Guard

```powershell
python src\training\train_guard.py
```

Expected model output:
- `models/finetuned-prompt-guard`

## 5. Milestone 4: Secure App + Final Evaluation

Run secure backend:

```powershell
python src\api\secure_app.py
```

Open secure UI:
- http://localhost:8001

Run final attack script:

```powershell
python eval\attack_secure.py
```

Expected:
- Final ASR drops near 0%.
- Injection prompts should be blocked with HTTP 400.

## Notes for Thesis Demo

- Keep both servers and evaluation logs to show before/after security impact.
- Demonstrate one benign prompt and one injection prompt live on UI.
- Report ASR numbers from both scripts in your thesis chapter.
