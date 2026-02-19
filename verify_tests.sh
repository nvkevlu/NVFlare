#!/bin/bash
# Quick script to verify all fixed tests pass

set -e

echo "=============================================="
echo "🧪 Running Fixed Recipe Tests"
echo "=============================================="
echo ""

cd "$(dirname "$0")"

echo "Python version: $(python3 --version)"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Testing Sklearn Recipes (12 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/unit_test/app_opt/sklearn/test_recipes.py -v --tb=short

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Testing SVM Assembler (5 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/unit_test/app_opt/sklearn/test_svm_assembler.py -v --tb=short

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  Testing XGBoost Bagging Recipe (8 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest tests/unit_test/app_opt/xgboost/test_xgb_bagging_recipe.py -v --tb=short

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  Testing Data Splits (18 tests)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pytest examples/advanced/sklearn-linear/test_data_splits.py -v --tb=short
pytest examples/advanced/sklearn-kmeans/test_data_splits.py -v --tb=short
pytest examples/advanced/sklearn-svm/test_data_splits.py -v --tb=short

echo ""
echo "=============================================="
echo "✅ All Tests Passed!"
echo "=============================================="
echo ""
echo "Summary:"
echo "  • Sklearn Recipe Tests: 12 passed"
echo "  • SVM Assembler Tests: 5 passed"
echo "  • XGBoost Recipe Tests: 8 passed"
echo "  • Data Split Tests: 18 passed"
echo "  • TOTAL: 43 tests passed"
echo ""
echo "Ready to commit! 🚀"


