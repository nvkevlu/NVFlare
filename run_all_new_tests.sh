#!/bin/bash
# Run all newly added tests to verify they pass before committing
set -e

echo "=============================================="
echo "🧪 Running All New Recipe Tests"
echo "=============================================="
echo ""

cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Unit Tests: Sklearn Recipes (15 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/unit_test/app_opt/sklearn/test_recipes.py -v

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Unit Tests: SVM Assembler (5 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/unit_test/app_opt/sklearn/test_svm_assembler.py -v

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  Unit Tests: XGBoost Bagging Recipe (8 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/unit_test/app_opt/xgboost/test_xgb_bagging_recipe.py -v

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  Unit Tests: Example Data Splits (18 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/unit_test/examples/sklearn-linear/test_data_splits.py -v
pytest tests/unit_test/examples/sklearn-kmeans/test_data_splits.py -v
pytest tests/unit_test/examples/sklearn-svm/test_data_splits.py -v

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5️⃣  Integration Tests: Sklearn Recipes (7 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/integration_test/test_sklearn_recipes_integration.py -v

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6️⃣  Integration Tests: XGBoost Recipe (8 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/integration_test/test_xgboost_recipe_integration.py -v

echo ""
echo "=============================================="
echo "✅ All 61 Tests Passed!"
echo "=============================================="
echo ""
echo "Test breakdown:"
echo "  • Unit Tests (Library Code): 28 tests"
echo "    - Sklearn recipes: 15"
echo "    - SVM assembler: 5"
echo "    - XGBoost recipe: 8"
echo "  • Unit Tests (Example Code): 18 tests"
echo "    - sklearn-linear: 8"
echo "    - sklearn-kmeans: 5"
echo "    - sklearn-svm: 5"
echo "  • Integration Tests: 15 tests"
echo "    - Sklearn recipes: 7"
echo "    - XGBoost recipe: 8"
echo ""
echo "📦 Ready to commit!"

