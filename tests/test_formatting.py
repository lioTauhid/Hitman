from hitman.core.formatting import fold_ranges, pretty_body


def test_fold_ranges_pair_brackets_of_pretty_json():
    text = pretty_body('{"a": {"b": [1, 2]}, "e": {}, "s": "x{", "t": "}"}', "JSON")
    lines = text.split("\n")
    assert fold_ranges(lines) == {0: len(lines) - 1, 1: 6, 2: 5}
    assert lines[6].strip() == "},"  # the closer keeps its trailing comma


def test_fold_ranges_skip_unbalanced_brackets():
    assert fold_ranges(["{", "  [", "  }", "]"]) == {1: 3}  # the stray "}" pairs with nothing
    assert fold_ranges(["[", "  {", "  }"]) == {1: 2}
