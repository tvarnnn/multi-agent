from agent_platform.orchestrator.model_schemas import CoderFileWrite
from agent_platform.orchestrator.stall_detection import (
    is_negligible_diff,
    is_repeated_identical_test_failure,
    is_repeated_review_rejection,
)


def test_negligible_diff_true_for_identical_writes():
    prev = (CoderFileWrite(path="app.py", content="x = 1"),)
    new = (CoderFileWrite(path="app.py", content="x = 1"),)
    assert is_negligible_diff(prev, new) is True


def test_negligible_diff_false_for_different_content():
    prev = (CoderFileWrite(path="app.py", content="x = 1"),)
    new = (CoderFileWrite(path="app.py", content="x = 2"),)
    assert is_negligible_diff(prev, new) is False


def test_negligible_diff_false_for_different_paths():
    prev = (CoderFileWrite(path="a.py", content="x = 1"),)
    new = (CoderFileWrite(path="b.py", content="x = 1"),)
    assert is_negligible_diff(prev, new) is False


def test_negligible_diff_false_when_either_side_is_empty_or_none():
    write = (CoderFileWrite(path="a.py", content="x"),)
    assert is_negligible_diff(None, write) is False
    assert is_negligible_diff((), write) is False
    assert is_negligible_diff((), ()) is False


def test_repeated_review_rejection_false_with_fewer_than_two_entries():
    assert is_repeated_review_rejection(()) is False
    assert is_repeated_review_rejection((("bug",),)) is False


def test_repeated_review_rejection_true_when_last_two_match():
    history = (("missing auth",), ("missing auth",))
    assert is_repeated_review_rejection(history) is True


def test_repeated_review_rejection_false_when_last_two_differ():
    history = (("missing auth",), ("different issue",))
    assert is_repeated_review_rejection(history) is False


def test_repeated_review_rejection_ignores_order_within_an_entry():
    history = (("issue a", "issue b"), ("issue b", "issue a"))
    assert is_repeated_review_rejection(history) is True


def test_repeated_review_rejection_false_when_both_entries_are_empty():
    assert is_repeated_review_rejection(((), ())) is False


def test_repeated_identical_test_failure_false_with_fewer_than_two_entries():
    assert is_repeated_identical_test_failure(()) is False
    assert is_repeated_identical_test_failure((("fail: test_x",),)) is False


def test_repeated_identical_test_failure_true_when_last_two_match():
    history = (("test.run exit_code=1",), ("test.run exit_code=1",))
    assert is_repeated_identical_test_failure(history) is True


def test_repeated_identical_test_failure_false_when_last_two_differ():
    history = (("test.run exit_code=1",), ("test.run exit_code=0",))
    assert is_repeated_identical_test_failure(history) is False


def test_repeated_identical_test_failure_false_when_both_are_trivially_empty():
    # An empty acceptance-criteria list produces empty details every
    # time by design (Phase 1's AcceptanceCriteriaFileValidator) - that
    # must never be mistaken for a repeated failure.
    assert is_repeated_identical_test_failure(((), ())) is False
