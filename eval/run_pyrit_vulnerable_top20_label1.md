# Run PyRIT test on vulnerable app (top 20 from label1 dataset)

This guide runs attack evaluation on vulnerable app using the first 20 prompts from:
- gendata/generated_label1_2000.jsonl

## 1) Open terminal A: start vulnerable app

```powershell
python src/api/vulnerable_app.py
```

Wait until API is ready at:
- http://localhost:8000

## 2) Open terminal B: set env vars for this run

```powershell
$env:EVAL_PROMPTS_FILE = "gendata/generated_label1_2000.jsonl"
$env:ATTACK_LIMIT = "20"
$env:ATTACK_LABELS = "1"
$env:USE_RULE_BASED_SCORER = "0"
$env:PYRIT_BATCH_SIZE = "1"
$env:RUNNING_STATS_EVERY = "5"
```

Notes:
- `EVAL_PROMPTS_FILE` points to your generated label1 dataset.
- `ATTACK_LIMIT=20` forces only first 20 prompts to be used.
- `ATTACK_LABELS=1` keeps only label 1 rows.
- `USE_RULE_BASED_SCORER=0` keeps PyRIT LLM judge mode.

## 3) Run vulnerable attack eval (PyRIT)

```powershell
python eval/attack_vulnerable.py
```

## 4) Expected outputs

After run, check:
- data/asr_baseline.json
- data/pyrit_memory.db

Quick view of baseline metrics:

```powershell
Get-Content data/asr_baseline.json
```

## 5) Optional cleanup (same terminal B)

```powershell
Remove-Item Env:EVAL_PROMPTS_FILE -ErrorAction SilentlyContinue
Remove-Item Env:ATTACK_LIMIT -ErrorAction SilentlyContinue
Remove-Item Env:ATTACK_LABELS -ErrorAction SilentlyContinue
Remove-Item Env:USE_RULE_BASED_SCORER -ErrorAction SilentlyContinue
Remove-Item Env:PYRIT_BATCH_SIZE -ErrorAction SilentlyContinue
Remove-Item Env:RUNNING_STATS_EVERY -ErrorAction SilentlyContinue
```
