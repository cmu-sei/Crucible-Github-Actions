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


def test_added_keys_take_their_defaults_with_strings_quoted():
    data = _roundtrip(
        textwrap.dedent(
            """\
            env:
              Existing__Key: ""
            """
        )
    )
    changed = patch_values(
        data,
        subkey=None,
        added={
            "Proxmox__GuestStateRefreshIntervalSeconds": LeafType.NUMBER,
            "Terraform__GenerateTopology": LeafType.BOOL,
            "Terraform__Secrets__Patterns__0": LeafType.STRING,
            "ClientSettings__CiteApiUrl": LeafType.STRING,
            "Not__InDefaults": LeafType.NUMBER,
        },
        removed=[],
        defaults={
            "Proxmox__GuestStateRefreshIntervalSeconds": 30,
            "Terraform__GenerateTopology": True,
            "Terraform__Secrets__Patterns__0": "^CASTER_SECRET_",
            "ClientSettings__CiteApiUrl": "http://localhost:4720/",
        },
    )
    assert changed is True
    assert _dump(data) == textwrap.dedent(
        """\
        env:
          Existing__Key: ""
          Proxmox__GuestStateRefreshIntervalSeconds: 30
          Terraform__GenerateTopology: true
          Terraform__Secrets__Patterns__0: "^CASTER_SECRET_"
          ClientSettings__CiteApiUrl: "http://localhost:4720/"
          Not__InDefaults: 0
        """
    )


def test_numbers_of_a_million_or_more_are_quoted():
    """Helm renders an unquoted 6000000000 as "6e+09", which .NET can't bind to a long."""
    data = _roundtrip("env:\n  Existing__Key: \"\"\n")
    added = {
        "IsoUpload__MaxFileSize": LeafType.NUMBER,
        "Exactly__AMillion": LeafType.NUMBER,
        "Large__Negative": LeafType.NUMBER,
        "Just__UnderAMillion": LeafType.NUMBER,
        "Some__Ratio": LeafType.NUMBER,
    }
    patch_values(
        data,
        subkey=None,
        added=added,
        removed=[],
        defaults={
            "IsoUpload__MaxFileSize": 6000000000,
            "Exactly__AMillion": 1000000,
            "Large__Negative": -2000000,
            "Just__UnderAMillion": 999999,
            "Some__Ratio": 0.5,
        },
    )
    assert _dump(data) == textwrap.dedent(
        """\
        env:
          Existing__Key: ""
          IsoUpload__MaxFileSize: "6000000000"
          Exactly__AMillion: "1000000"
          Large__Negative: "-2000000"
          Just__UnderAMillion: 999999
          Some__Ratio: 0.5
        """
    )


def test_defaults_do_not_change_a_key_the_chart_already_sets():
    data = _roundtrip("env:\n  Proxmox__GuestStateParallelism: 4\n")
    changed = patch_values(
        data,
        subkey=None,
        added={"Proxmox__GuestStateParallelism": LeafType.NUMBER},
        removed=[],
        defaults={"Proxmox__GuestStateParallelism": 8},
    )
    assert changed is False
    assert _dump(data) == "env:\n  Proxmox__GuestStateParallelism: 4\n"
