import io
import json
import textwrap

from ruamel.yaml import YAML

from settings_sync.flatten import LeafType
from settings_sync.patch_angular import finalize_dump, patch_values

yaml = YAML()
yaml.preserve_quotes = True


def _roundtrip(text: str):
    return yaml.load(io.StringIO(text))


def _dump(data) -> str:
    buf = io.StringIO()
    yaml.dump(data, buf)
    return finalize_dump(buf.getvalue(), data)


def test_updates_stringified_settings_json_adding_blank_by_type():
    src = textwrap.dedent(
        """\
        settings: '{"ApiUrl": ""}'
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey=None,
        added={
            "/OIDCSettings/authority": LeafType.STRING,
            "/OIDCSettings/automaticSilentRenew": LeafType.BOOL,
        },
        removed=[],
    )
    assert changed is True
    settings_str = data["settings"]
    parsed = json.loads(settings_str)
    assert parsed["OIDCSettings"]["authority"] == ""
    assert parsed["OIDCSettings"]["automaticSilentRenew"] is False
    assert parsed["ApiUrl"] == ""


def test_removes_key_from_stringified_settings_json():
    src = textwrap.dedent(
        """\
        settings: '{"Keep": "", "Drop": ""}'
        """
    )
    data = _roundtrip(src)
    changed = patch_values(data, subkey=None, added={}, removed=["/Drop"])
    assert changed is True
    parsed = json.loads(data["settings"])
    assert parsed == {"Keep": ""}


def test_updates_settingsYaml_appending_commented_lines():
    src = textwrap.dedent(
        """\
        settingsYaml:
          # ApiUrl: ""
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey=None,
        added={"/OIDCSettings/authority": LeafType.STRING},
        removed=[],
    )
    assert changed is True
    out = _dump(data)
    assert "# OIDCSettings:" in out
    assert '#   authority: ""' in out


def test_skips_when_neither_settings_nor_settingsYaml_present():
    src = "image: {}\n"
    data = _roundtrip(src)
    changed = patch_values(
        data, subkey=None, added={"/X": LeafType.STRING}, removed=[]
    )
    assert changed is False


def test_updates_both_blocks_when_both_present():
    src = textwrap.dedent(
        """\
        settings: '{}'
        settingsYaml: {}
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data, subkey=None, added={"/A": LeafType.STRING}, removed=[]
    )
    assert changed is True
    assert json.loads(data["settings"]) == {"A": ""}
    out = _dump(data)
    assert '# A: ""' in out


def test_operates_under_subkey_in_parent_values():
    src = textwrap.dedent(
        """\
        player-ui:
          settings: '{}'
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data, subkey="player-ui", added={"/A": LeafType.BOOL}, removed=[]
    )
    assert changed is True
    assert json.loads(data["player-ui"]["settings"]) == {"A": False}


def test_settings_yaml_splice_scoped_to_target_subkey():
    src = textwrap.dedent(
        """\
        player-api:
          env:
            Existing__Key: ""
        player-ui:
          settingsYaml: {}
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey="player-api",
        added={"/OIDCSettings/authority": LeafType.STRING},
        removed=[],
    )
    # player-api has no settings/settingsYaml block, so no change should occur
    # and the player-ui settingsYaml must NOT be spliced into.
    assert changed is False
    out = _dump(data)
    assert "OIDCSettings" not in out
    assert "authority" not in out


def test_settings_yaml_splice_targets_correct_sibling_block():
    src = textwrap.dedent(
        """\
        player-api:
          settingsYaml: {}
        player-ui:
          settingsYaml: {}
        """
    )
    data = _roundtrip(src)
    changed = patch_values(
        data,
        subkey="player-ui",
        added={"/OIDCSettings/authority": LeafType.STRING},
        removed=[],
    )
    assert changed is True
    out = _dump(data)
    # The splice must land under player-ui, not under player-api.
    api_idx = out.index("player-api:")
    ui_idx = out.index("player-ui:")
    oidc_idx = out.index("# OIDCSettings:")
    assert ui_idx < oidc_idx
    # And the player-api block (between api_idx and ui_idx) must not contain it.
    assert "OIDCSettings" not in out[api_idx:ui_idx]
