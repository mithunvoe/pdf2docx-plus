"""Benchmark metric unit tests."""

from __future__ import annotations

import pytest

from bench.metrics import kendall_tau, text_char_accuracy, text_f1


@pytest.mark.unit
def test_text_f1_identical() -> None:
    assert text_f1("hello world", "hello world") == pytest.approx(1.0)


@pytest.mark.unit
def test_text_f1_empty_both() -> None:
    assert text_f1("", "") == 1.0


@pytest.mark.unit
def test_text_f1_empty_one() -> None:
    assert text_f1("hello", "") == 0.0
    assert text_f1("", "hello") == 0.0


@pytest.mark.unit
def test_text_f1_partial_overlap() -> None:
    # word-level: one shared token ('cat') out of 2+2 = 0.5
    score = text_f1("the cat sat", "the dog ran")
    assert 0.0 < score < 1.0


@pytest.mark.unit
def test_text_f1_case_insensitive() -> None:
    assert text_f1("Hello WORLD", "hello world") == pytest.approx(1.0)


@pytest.mark.unit
def test_text_char_accuracy_identical() -> None:
    assert text_char_accuracy("hello", "hello") == pytest.approx(1.0)


@pytest.mark.unit
def test_text_char_accuracy_partial() -> None:
    score = text_char_accuracy("hello", "help")
    assert 0.0 < score < 1.0


@pytest.mark.unit
def test_text_char_accuracy_empty() -> None:
    assert text_char_accuracy("", "") == 1.0
    assert text_char_accuracy("a", "") == 0.0


@pytest.mark.unit
def test_kendall_tau_identical() -> None:
    assert kendall_tau([0, 1, 2, 3], [0, 1, 2, 3]) == pytest.approx(1.0)


@pytest.mark.unit
def test_kendall_tau_reversed() -> None:
    assert kendall_tau([3, 2, 1, 0], [0, 1, 2, 3]) == pytest.approx(-1.0)


@pytest.mark.unit
def test_kendall_tau_mismatched_sets() -> None:
    assert kendall_tau([0, 1], [2, 3]) == 0.0
