import io
import textwrap

from ruamel.yaml import YAML

from settings_sync.flatten import LeafType
from settings_sync.patch_dotnet import patch_values

yaml = YAML()
yaml.preserve_quotes = True


def _roundtrip(text: str):
    return yaml.load(io.StringIO(text))


def _dump(data) -> str:
    buf = io.StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def test_adds_new_keys_at_end_of_env_block():
    src = textwrap.dedent(
        """\
        env:
          Existing__Key: ""
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey=None,
        added={
            "Authorization__NewSetting": LeafType.STRING,
            "Logging__Enabled": LeafType.BOOL,
        },
        removed=[],
    )
    assert changed is True
    out = _dump(data)
    assert 'Authorization__NewSetting: ""' in out
    assert "Logging__Enabled: false" in out
    assert out.index("Existing__Key") < out.index("Authorization__NewSetting")


def test_removes_existing_keys():
    src = textwrap.dedent(
        """\
        env:
          Keep__Me: ""
          Remove__Me: ""
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data, subkey=None, added={}, removed=["Remove__Me"]
    )
    assert changed is True
    out = _dump(data)
    assert "Keep__Me" in out
    assert "Remove__Me" not in out


def test_creates_env_block_when_missing_at_root():
    src = "image: {}\n"
    data = _roundtrip(src)
    changed = patch_values(
        data, subkey=None, added={"New__Key": LeafType.STRING}, removed=[]
    )
    assert changed is True
    out = _dump(data)
    assert "env:" in out
    assert 'New__Key: ""' in out


def test_skips_parent_when_env_block_missing_under_subkey():
    src = textwrap.dedent(
        """\
        player-api:
          image:
            repository: x
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey="player-api",
        added={"New__Key": LeafType.STRING},
        removed=[],
    )
    assert changed is False
    assert "env:" not in _dump(data)


def test_updates_env_block_under_subkey_when_present():
    src = textwrap.dedent(
        """\
        player-api:
          env:
            Existing__Key: ""
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey="player-api",
        added={"New__Key": LeafType.NUMBER},
        removed=[],
    )
    assert changed is True
    out = _dump(data)
    assert "New__Key: 0" in out


def test_empty_diff_returns_false_and_noop():
    src = "env:\n  Keep: \"\"\n"
    data = _roundtrip(src)
    changed = patch_values(data, subkey=None, added={}, removed=[])
    assert changed is False
    assert _dump(data) == src


def test_scalar_array_added_as_index_zero_string():
    src = "env: {}\n"
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey=None,
        added={"CorsPolicy__Origins__0": LeafType.STRING},
        removed=[],
    )
    assert changed is True
    assert 'CorsPolicy__Origins__0: ""' in _dump(data)
