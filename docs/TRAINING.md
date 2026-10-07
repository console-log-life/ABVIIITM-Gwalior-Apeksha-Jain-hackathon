# Training the models on a free GPU

The notebook `src/notebooks/train_models.ipynb` fine-tunes two models on public, human-labelled datasets (MIT licence):

| Model | Base | Training data | Held-out test |
|---|---|---|---|
| Sentiment | `ProsusAI/finbert` | `zeroshot/twitter-financial-news-sentiment`, 8,384 train / 932 dev | 2,388 |
| Events | `distilroberta-base` | `zeroshot/twitter-financial-news-topic`, 14,149 train / 1,571 dev | 4,117 |

It runs top to bottom without edits and expects a T4 GPU. Training needs a few minutes on the GPU; with downloads,
plan for about 20–30 minutes. The output is **`trained_models.zip`** (under 1 GB).

The notebook rebuilds the splits with the repository's own code and stops with "split checksum differs" if they don't
match `data/splits/*.json`. That check guarantees the test examples are the same ones we evaluate locally.

---

## Option A: Kaggle (recommended: 30 free GPU hours a week)

1. Sign in at <https://www.kaggle.com>. Your account must be **phone-verified** to use GPUs and the internet:
   avatar (top right) → **Settings** → **Phone verification**.
2. Top left, click **+ Create** → **New Notebook**.
3. In the notebook menu, click **File** → **Import Notebook**. Choose **File** in the dialog, drag in
   `src/notebooks/train_models.ipynb` from the repository folder
   (`E:\GT LAB\PROJECTS\risk-signal-engine\notebooks\train_models.ipynb`), and click **Import**.
4. Open the right-hand panel (the **›** arrow at the top right if it is hidden). Under **Session options**:
   - **Accelerator** → **GPU T4 x2** (or **GPU T4**). Confirm with **Turn on GPU**.
   - **Internet** → **On**. Without internet the notebook cannot download the datasets and models.
5. Optional: if you have a Hugging Face account, paste a *read* token into `HF_TOKEN = ""` in the first code cell. You
   can leave it empty.
6. Click **Run All** (the ⏩ button in the toolbar, or **Run** → **Run all**).
7. Wait until the last cell prints `done in … min on Tesla T4; zip: /kaggle/working/trained_models.zip (… MB)`.
   If any cell shows a red error, copy the error text and send it to me.
8. Download the zip: right-hand panel → **Output** (or the **Data** tab → **Output** → `/kaggle/working`) → hover over
   `trained_models.zip` → **⋮** → **Download**.
   If the file is not listed, click the refresh icon in the Output section.
9. Put the zip in the project folder (`E:\GT LAB\PROJECTS\risk-signal-engine\trained_models.zip`; it is git-ignored)
   and tell me. I'll run `python src/scripts/import_trained_models.py trained_models.zip`.

## Option B: Google Colab

1. Open <https://colab.research.google.com> → **File** → **Upload notebook** → choose `src/notebooks/train_models.ipynb`.
2. **Runtime** → **Change runtime type** → **Hardware accelerator: T4 GPU** → **Save**.
3. **Runtime** → **Run all**. If Colab warns that the notebook was not authored by Google, click **Run anyway**.
4. When the last cell prints `done …`, open the **Files** panel (folder icon on the left). `trained_models.zip` is in
   `/content`. Right-click it → **Download**.
5. Continue with step 9 above.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `split checksum differs` | The dataset changed on the hub. The notebook pins the dataset revision, so this should not happen; send me the message |
| `ConnectionError` / `LocalEntryNotFoundError` | Kaggle **Internet** is off (step 4), or Hugging Face is rate-limiting; add `HF_TOKEN` |
| `CUDA out of memory` | Set `BATCH = 16` in the first code cell and **Run All** again |
| No GPU listed on Kaggle | The account is not phone-verified (step 1), or the weekly GPU quota is used up |
| pip dependency warnings | Harmless as long as the next cells run |

## What the zip contains

- `trained_models/sentiment_finbert_ft/` and `trained_models/event_distilroberta_ft/` (Hugging Face format,
  safetensors), each with a `risk_engine_labels.json` that maps the model's labels to ours;
- `metrics.json`: base vs fine-tuned on the held-out test split (n, accuracy, macro-F1, per-class F1, confusion
  matrices), dev scores, training time and GPU;
- `confusion_*.png`;
- `predictions_test.json`: the notebook's test predictions. The import script re-predicts a sample on the laptop and
  checks they match, which catches any label-mapping mistake.

The rule-based event classifier is evaluated on the same test split locally (`src/scripts/evaluate.py`), because it needs
the repository code.

## Reproducing the splits locally

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe scripts\datasets\prepare_public.py      # data/splits/*.json + data/external/*.csv
.venv\Scripts\python.exe scripts\build_training_notebook.py      # regenerates the notebook from the repo code
```
