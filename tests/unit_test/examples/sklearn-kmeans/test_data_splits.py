# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for data splitting logic in sklearn-kmeans example."""

import sys
from pathlib import Path

# Add sklearn-kmeans example directory to path to import calculate_data_splits
example_dir = Path(__file__).parent.parent.parent.parent.parent / "examples" / "advanced" / "sklearn-kmeans"
sys.path.insert(0, str(example_dir))

from job import calculate_data_splits


class TestKMeansDataSplits:
    """Tests for K-Means calculate_data_splits function."""

    def test_splits_non_overlapping(self):
        """Test that data splits are non-overlapping."""
        n_clients = 3
        splits = calculate_data_splits(n_clients)

        # Extract all train ranges
        train_ranges = []
        for site_name, split in splits.items():
            train_ranges.append((split["train_start"], split["train_end"]))

        # Check no overlaps
        for i in range(len(train_ranges)):
            for j in range(i + 1, len(train_ranges)):
                start1, end1 = train_ranges[i]
                start2, end2 = train_ranges[j]
                assert end1 <= start2 or end2 <= start1, f"Ranges {train_ranges[i]} and {train_ranges[j]} overlap"

    def test_splits_cover_all_training_data(self):
        """Test that splits cover all training data without gaps."""
        n_clients = 3
        total_size = 150
        train_fraction = 0.8
        splits = calculate_data_splits(n_clients, total_size, train_fraction)

        train_size = int(total_size * train_fraction)

        # Sort ranges by start position
        train_ranges = sorted(
            [(split["train_start"], split["train_end"]) for split in splits.values()], key=lambda x: x[0]
        )

        # First range should start at 0
        assert train_ranges[0][0] == 0

        # Last range should end at train_size
        assert train_ranges[-1][1] == train_size

        # Check for gaps between consecutive ranges
        for i in range(len(train_ranges) - 1):
            assert train_ranges[i][1] == train_ranges[i + 1][0], f"Gap between ranges {i} and {i+1}"

    def test_splits_shared_validation(self):
        """Test that all clients share the same validation set."""
        n_clients = 3
        total_size = 150
        train_fraction = 0.8
        splits = calculate_data_splits(n_clients, total_size, train_fraction)

        expected_valid_start = int(total_size * train_fraction)

        # All clients should have same validation range
        for site_name, split in splits.items():
            assert split["valid_start"] == expected_valid_start, f"{site_name} has incorrect valid_start"
            assert split["valid_end"] == total_size, f"{site_name} has incorrect valid_end"

    def test_splits_correct_number_of_clients(self):
        """Test that correct number of splits are generated."""
        for n_clients in [2, 3, 5]:
            splits = calculate_data_splits(n_clients)
            assert len(splits) == n_clients, f"Expected {n_clients} splits, got {len(splits)}"

    def test_splits_with_different_train_fractions(self):
        """Test splits with different train/validation split ratios."""
        n_clients = 3
        total_size = 150

        for train_fraction in [0.6, 0.7, 0.8, 0.9]:
            splits = calculate_data_splits(n_clients, total_size, train_fraction)
            expected_valid_start = int(total_size * train_fraction)

            for split in splits.values():
                assert split["valid_start"] == expected_valid_start
                assert split["valid_end"] == total_size
                assert split["train_end"] <= expected_valid_start
