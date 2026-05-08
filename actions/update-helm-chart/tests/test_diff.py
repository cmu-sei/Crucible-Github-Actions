from settings_sync.diff import compute_diff, Diff
from settings_sync.flatten import LeafType


def test_added_and_removed_computed_from_two_maps():
    prev = {"A": LeafType.STRING, "B": LeafType.BOOL}
    new = {"B": LeafType.BOOL, "C": LeafType.NUMBER}
    diff = compute_diff(prev, new)
    assert diff == Diff(added={"C": LeafType.NUMBER}, removed=["A"])


def test_identical_maps_yield_empty_diff():
    prev = {"A": LeafType.STRING}
    new = {"A": LeafType.STRING}
    diff = compute_diff(prev, new)
    assert diff.added == {}
    assert diff.removed == []


def test_empty_previous_means_everything_added():
    prev: dict = {}
    new = {"A": LeafType.STRING, "B": LeafType.BOOL}
    diff = compute_diff(prev, new)
    assert diff.added == {"A": LeafType.STRING, "B": LeafType.BOOL}
    assert diff.removed == []


def test_type_change_is_not_a_modification():
    prev = {"A": LeafType.STRING}
    new = {"A": LeafType.BOOL}
    diff = compute_diff(prev, new)
    assert diff.added == {}
    assert diff.removed == []


def test_removed_list_sorted_alphabetically():
    prev = {"Z": LeafType.STRING, "A": LeafType.STRING, "M": LeafType.STRING}
    new: dict = {}
    diff = compute_diff(prev, new)
    assert diff.removed == ["A", "M", "Z"]
