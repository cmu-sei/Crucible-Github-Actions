import json

from settings_sync.jsonc import strip_jsonc_comments


def test_strips_line_comments_outside_strings():
    src = '{\n  "a": 1, // trailing\n  "b": 2\n}'
    result = strip_jsonc_comments(src)
    assert json.loads(result) == {"a": 1, "b": 2}


def test_preserves_double_slashes_inside_strings():
    src = '{"url": "http://example.com"}'
    result = strip_jsonc_comments(src)
    assert json.loads(result) == {"url": "http://example.com"}


def test_preserves_escaped_quotes_in_strings():
    src = '{"s": "a\\"b // not a comment"}'
    result = strip_jsonc_comments(src)
    assert json.loads(result) == {"s": 'a"b // not a comment'}


def test_strips_commented_out_object_leaving_empty_array():
    src = '{\n  "seeds": [\n    // { "name": "x" }\n  ]\n}'
    result = strip_jsonc_comments(src)
    assert json.loads(result) == {"seeds": []}


def test_strips_block_comments():
    src = '{ "a": 1 /* inline */, "b": 2 }'
    result = strip_jsonc_comments(src)
    assert json.loads(result) == {"a": 1, "b": 2}
