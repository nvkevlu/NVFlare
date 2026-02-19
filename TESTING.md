# Recipe Testing Guide

This document describes the test coverage for NVFlare recipe examples.

## Test Structure

Tests are organized into three categories:

### 1. Unit Tests (`tests/unit_test/`)

Unit tests verify individual components and recipe configurations in isolation.

#### Sklearn Recipe Tests (`tests/unit_test/app_opt/sklearn/`)

- **`test_recipes.py`**: Tests for core sklearn recipe classes
  - `TestSklearnFedAvgRecipe`: Linear model recipe configuration
    - Creation with default and custom parameters
    - String vs. dictionary train_args
    - Model hyperparameters (model_params)
    - None model_params handling
  - `TestKMeansFedAvgRecipe`: K-Means clustering recipe
    - Default and custom cluster counts
    - Per-client train_args
    - Different cluster configurations
  - `TestSVMFedAvgRecipe`: SVM recipe
    - All kernel types (linear, poly, rbf, sigmoid)
    - Both backends (sklearn, cuml)
    - Pydantic validation for invalid kernels/backends
    - Per-client train_args

- **`test_svm_assembler.py`**: Tests for SVM support vector assembler
  - Valid and invalid kernel types
  - get_model_params method
  - Default kernel configuration

#### XGBoost Recipe Tests (`tests/unit_test/app_opt/xgboost/`)

- **`test_xgb_bagging_recipe.py`**: Tests for XGBoost bagging recipe
  - Default and custom XGBoost parameters
  - GPU configuration
  - Validation of num_client_bagging
  - Subsample ratio validation (0 < value <= 1)
  - Learning rate modes (uniform, scaled)
  - Invalid configuration error handling

### 2. Integration Tests (`tests/integration_test/`)

Integration tests verify end-to-end recipe configuration and multi-component interactions.

- **`test_sklearn_recipes_integration.py`**: Sklearn recipe integration tests
  - Per-client data split configurations
  - All kernel types for SVM
  - Both backends (sklearn, cuml)
  - Shared vs. per-client train_args
  - Recipe instance independence

- **`test_xgboost_recipe_integration.py`**: XGBoost recipe integration tests
  - Random Forest recipe configuration
  - Scaled learning rate mode
  - GPU configuration
  - Different XGBoost objectives
  - Parameter validation enforcement
  - Varying client counts
  - Custom tree hyperparameters

### 3. Example-Specific Tests (`tests/unit_test/examples/`)

These tests verify the data splitting logic in each example's `job.py`.

- **`tests/unit_test/examples/sklearn-linear/test_data_splits.py`**
  - Non-overlapping train splits
  - Complete coverage of training data
  - Shared validation set across clients
  - Correct number of client splits
  - Site naming convention
  - Approximately equal split sizes
  - Custom dataset sizes

- **`tests/unit_test/examples/sklearn-kmeans/test_data_splits.py`**
  - Non-overlapping train splits
  - Complete coverage of training data
  - Shared validation set
  - Different train/validation fractions

- **`tests/unit_test/examples/sklearn-svm/test_data_splits.py`**
  - Non-overlapping train splits
  - Complete coverage of training data
  - Shared validation set
  - Site naming convention

## Running Tests

### Run All Tests

```bash
pytest
```

### Run Specific Test Categories

```bash
# Unit tests only
pytest tests/unit_test/

# Integration tests only
pytest tests/integration_test/

# Example-specific tests
pytest tests/unit_test/examples/sklearn-linear/test_data_splits.py
pytest tests/unit_test/examples/sklearn-kmeans/test_data_splits.py
pytest tests/unit_test/examples/sklearn-svm/test_data_splits.py
```

### Run Tests for Specific Recipes

```bash
# Sklearn recipes
pytest tests/unit_test/app_opt/sklearn/

# XGBoost recipes
pytest tests/unit_test/app_opt/xgboost/

# SVM-specific
pytest tests/unit_test/app_opt/sklearn/test_svm_assembler.py
```

### Run with Coverage

```bash
pytest --cov=nvflare.app_opt.sklearn --cov=nvflare.app_opt.xgboost
```

### Run with Verbose Output

```bash
pytest -v
```

## Test Coverage Summary

| Component | Unit Tests | Integration Tests | Data Split Tests |
|-----------|------------|-------------------|------------------|
| SklearnFedAvgRecipe | ✅ | ✅ | ✅ |
| KMeansFedAvgRecipe | ✅ | ✅ | ✅ |
| SVMFedAvgRecipe | ✅ | ✅ | ✅ |
| SVMAssembler | ✅ | ✅ | N/A |
| XGBBaggingRecipe | ✅ | ✅ | N/A |

## Key Test Features

### 1. Per-Client Data Splitting

All sklearn examples test that:
- Data splits are non-overlapping across clients
- All training data is covered without gaps
- Validation set is shared across all clients
- Site naming follows `site-1`, `site-2`, etc. convention

### 2. Pydantic Validation

Tests verify that:
- Invalid kernel types raise `ValueError` for SVM
- Invalid backend types raise `ValueError` for SVM
- Invalid lr_mode raises `ValueError` for XGBoost
- Subsample ratios outside (0, 1] raise `ValueError`
- num_client_bagging < min_clients raises `ValueError`

### 3. Configuration Flexibility

Tests confirm recipes support:
- String train_args (shared across clients)
- Dictionary train_args (per-client customization)
- Optional model parameters (None or dict)
- Various hyperparameter combinations

### 4. Recipe Independence

Tests verify that multiple recipe instances:
- Don't share state
- Can have different configurations
- Don't interfere with each other

## Adding New Tests

When adding new recipe examples, create:

1. **Unit tests** in `tests/unit_test/app_opt/<framework>/`
   - Test recipe creation with various parameters
   - Test Pydantic validation
   - Test parameter edge cases

2. **Integration tests** in `tests/integration_test/`
   - Test end-to-end configuration
   - Test multi-component interactions
   - Test with realistic parameter combinations

3. **Example-specific tests** in `tests/unit_test/examples/`
   - Test `calculate_data_splits()` function
   - Verify non-overlapping splits
   - Verify complete data coverage

## Continuous Integration

All tests run automatically on:
- Pull requests
- Commits to main branches
- Pre-commit hooks (via `pre-commit install`)

Tests must pass before code can be merged.
