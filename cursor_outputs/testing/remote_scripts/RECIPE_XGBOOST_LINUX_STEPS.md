# Recipe API XGBoost (advanced example) — exact Linux steps

Venv and run for **Recipe-based** job only (HIGGS, 2 sites, `job.py`). All fixes must be in repo (e.g. class-level adaptor cache in `fed_executor.py`).

**Paths:** `REPO_DIR=/localhome/local-kevlu/nvflare_testing/NVFlare` (change if your repo is elsewhere.)

---

## 1. Rename corrupted venv (if present)

```bash
REPO_DIR="/localhome/local-kevlu/nvflare_testing/NVFlare"
cd "$REPO_DIR"
[ -d xgb_test_venv ] && mv xgb_test_venv xgb_test_venv.corrupted
```

---

## 2. Create new venv and install (Recipe stack only)

```bash
cd "$REPO_DIR"
python3 -m venv xgb_test_venv
source xgb_test_venv/bin/activate
pip install --upgrade pip
pip install -e .
cd examples/advanced/xgboost
grep -v "^nvflare" requirements.txt | pip install -r /dev/stdin
```

---

## 3. Confirm federated XGBoost and fix

```bash
python3 -c "import xgboost.federated; print('federated OK')"
grep -q _adaptor_cache "$REPO_DIR/nvflare/app_opt/xgboost/histogram_based_v2/fed_executor.py" && echo "adaptor cache fix present"
```

---

## 4. HIGGS data and splits

- **CSV:** `$REPO_DIR/xgboost_test_data/HIGGS.csv` (plain CSV; if gzip, `mv HIGGS.csv HIGGS.csv.gz && gunzip HIGGS.csv.gz`).
- **Splits:** `job.py` uses `dataset_path = {data_root}_horizontal/{site_num}_{split_method}`. So use `data_root` = dir under which you have `..._horizontal/2_uniform`. Generate once:

```bash
cd "$REPO_DIR"
source xgb_test_venv/bin/activate
FEDXGB="$REPO_DIR/examples/advanced/xgboost/fedxgb"
DATA_ROOT="$REPO_DIR/xgboost_test_data"
HIGGS_CSV="$DATA_ROOT/HIGGS.csv"
# job.py expects data_root such that {data_root}_horizontal/2_uniform exists
mkdir -p "$DATA_ROOT/splits_horizontal"
cd "$FEDXGB"
python3 utils/prepare_data_horizontal.py --data_path "$HIGGS_CSV" --site_num 2 --size_total 11000000 --size_valid 1000000 --split_method uniform --out_path "$DATA_ROOT/splits_horizontal/2_uniform"
```

So `data_root` for the run must be `$REPO_DIR/xgboost_test_data/splits` (then `splits_horizontal/2_uniform` is used).

---

## 5. Run Recipe job

```bash
cd "$REPO_DIR"
source xgb_test_venv/bin/activate
cd examples/advanced/xgboost/fedxgb
python3 job.py --site_num 2 --round_num 2 --split_method uniform --data_root "$REPO_DIR/xgboost_test_data/splits"
```

(Use your actual `REPO_DIR`; e.g. `/localhome/local-kevlu/nvflare_testing/NVFlare`.)

---

## 6. Success

- Logs show `got my rank: 0`, `got my rank: 1`, `successfully configured client site-1`, `site-2`, `successfully configured clients ['site-1', 'site-2']`.
- No `rank not set` or `failed to start adaptor`.
- Training runs and completes.

If you still see `rank not set`, the process must be loading `fed_executor.py` from this repo (check with `python3 -c "import nvflare.app_opt.xgboost.histogram_based_v2.fed_executor as m; print(m.__file__)"`).
