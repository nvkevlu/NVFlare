# Tutorial 10.1 Fed XGBoost — Linux commands only (no notebook)

Run these in order on your Linux machine. Paths use the same base as earlier: `/localhome/local-kevlu/nvflare_testing/NVFlare`. Change that if your repo lives elsewhere.

---

## Paths (set once)

```bash
REPO_DIR="/localhome/local-kevlu/nvflare_testing/NVFlare"
TUTORIAL_DIR="${REPO_DIR}/examples/tutorials/self-paced-training/part-4_advanced_federated_learning/chapter-10_federated_XGBoost/10.1_fed_xgboost"
DATASET_DIR="/tmp/nvflare/dataset"
SPLIT_DIR="/tmp/nvflare/dataset/xgb_dataset"
```

---

## 1. Go to repo and activate venv

(If you don’t have `xgb_test_venv` yet, run `cursor_outputs/testing/remote_scripts/setup_xgboost_testing.sh` from repo root first.)

```bash
cd "$REPO_DIR"
source xgb_test_venv/bin/activate
```

---

## 2. Install tutorial deps (same federated XGBoost as setup script)

```bash
cd "$TUTORIAL_DIR"
pip install -r requirements.txt
```

---

## 3. Download Credit Card data into the path the script expects

```bash
mkdir -p "$DATASET_DIR"
python3 -c "import kagglehub; p=kagglehub.dataset_download('mlg-ulb/creditcardfraud'); print(p)"
```

Copy the printed path, then:

```bash
cp "<PASTE_PATH_HERE>/creditcard.csv" "$DATASET_DIR/creditcard.csv"
```

---

## 4. Generate data splits (same as notebook “Data Preparation”)

Must be run from the tutorial dir so `utils/` and script paths are correct.

```bash
cd "$TUTORIAL_DIR"
bash prepare_data.sh
```

Output goes to `$SPLIT_DIR` (`base_xgb_data`, `horizontal_xgb_data`, `vertical_xgb_data`). You should see messages about train/valid/test and site splits.

---

## 5. Run the federated jobs (same as notebook “Experiments”)

Still in `$TUTORIAL_DIR`:

```bash
# Horizontal histogram (run this first to verify)
python3 xgb_fl_job.py --training_algo histogram --data_split_mode horizontal
```

Then the rest (optional):

```bash
python3 xgb_fl_job.py --training_algo cyclic --data_split_mode horizontal
python3 xgb_fl_job.py --training_algo bagging --data_split_mode horizontal
python3 xgb_fl_job.py --training_algo histogram --data_split_mode vertical
```

---

## 6. Success

- No `rank not set` or `failed to start adaptor`.
- Logs show clients configured (site-1, site-2, site-3) and training running.
- Results under `/tmp/nvflare/workspace/fedxgb/` (e.g. `works` for TensorBoard).

If you see `RuntimeError: cannot start - my rank is not set`, the class-level adaptor cache fix must be in `nvflare/app_opt/xgboost/histogram_based_v2/fed_executor.py` on this machine (copy from your repo or scp the file).

---

## One-shot copy-paste (after setting REPO_DIR)

Assumes Credit Card CSV is already at `$DATASET_DIR/creditcard.csv`. If not, do step 3 first.

```bash
REPO_DIR="/localhome/local-kevlu/nvflare_testing/NVFlare"
TUTORIAL_DIR="${REPO_DIR}/examples/tutorials/self-paced-training/part-4_advanced_federated_learning/chapter-10_federated_XGBoost/10.1_fed_xgboost"
DATASET_DIR="/tmp/nvflare/dataset"

cd "$REPO_DIR"
source xgb_test_venv/bin/activate
cd "$TUTORIAL_DIR"
pip install -r requirements.txt
bash prepare_data.sh
python3 xgb_fl_job.py --training_algo histogram --data_split_mode horizontal
```

Then run cyclic, bagging, vertical as in step 5 if you want.
