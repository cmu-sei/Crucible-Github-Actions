from settings_sync.flatten import (
    flatten_angular,
    flatten_dotnet,
    flatten_dotnet_conf,
    LeafType,
)


def test_dotnet_flattens_nested_scalars():
    data = {
        "PathBase": "",
        "Authorization": {"Authority": "x", "RequireHttpsMetadata": False},
    }
    result = flatten_dotnet(data)
    assert result == {
        "PathBase": LeafType.STRING,
        "Authorization__Authority": LeafType.STRING,
        "Authorization__RequireHttpsMetadata": LeafType.BOOL,
    }


def test_dotnet_scalar_array_emits_single_index_zero():
    data = {"CorsPolicy": {"Origins": ["http://a", "http://b"]}}
    result = flatten_dotnet(data)
    assert result == {"CorsPolicy__Origins__0": LeafType.STRING}


def test_dotnet_empty_container_is_skipped():
    data = {"SeedData": {"Permissions": [], "Roles": {}}}
    result = flatten_dotnet(data)
    assert result == {}


def test_dotnet_number_and_bool_types():
    data = {"SignalR": {"BufferSize": 100000, "Enabled": True}}
    result = flatten_dotnet(data)
    assert result == {
        "SignalR__BufferSize": LeafType.NUMBER,
        "SignalR__Enabled": LeafType.BOOL,
    }


def test_angular_flattens_to_json_pointer_paths():
    data = {
        "ApiUrl": "",
        "OIDCSettings": {"authority": "", "automaticSilentRenew": True},
    }
    result = flatten_angular(data)
    assert result == {
        "/ApiUrl": LeafType.STRING,
        "/OIDCSettings/authority": LeafType.STRING,
        "/OIDCSettings/automaticSilentRenew": LeafType.BOOL,
    }


def test_angular_scalar_array_emits_index_zero_pointer():
    data = {"Scopes": ["openid", "profile"]}
    result = flatten_angular(data)
    assert result == {"/Scopes/0": LeafType.STRING}


def test_angular_empty_container_skipped():
    data = {"Empty": [], "AlsoEmpty": {}}
    result = flatten_angular(data)
    assert result == {}


def test_dotnet_conf_treats_every_line_as_string_leaf():
    raw = """\
# PathBase =
# Oidc__Audience = topomojo-api
# Database__Provider = InMemory
"""
    result = flatten_dotnet_conf(raw)
    assert result == {
        "PathBase": LeafType.STRING,
        "Oidc__Audience": LeafType.STRING,
        "Database__Provider": LeafType.STRING,
    }


def test_dotnet_conf_ignores_section_dividers_and_blank_lines():
    raw = """\
####################
## AppSettings
####################

## Some descriptive comment
# Oidc__Authority = http://localhost:5000

####################
## Database
####################
# Database__Provider = InMemory
"""
    result = flatten_dotnet_conf(raw)
    assert result == {
        "Oidc__Authority": LeafType.STRING,
        "Database__Provider": LeafType.STRING,
    }


def test_dotnet_conf_uncommented_lines_also_count_as_settings():
    raw = """\
PathBase = /api
# Oidc__Audience = topomojo-api
"""
    result = flatten_dotnet_conf(raw)
    assert result == {
        "PathBase": LeafType.STRING,
        "Oidc__Audience": LeafType.STRING,
    }


def test_dotnet_conf_blank_value_still_emits_key():
    raw = "# Database__AdminId =\n"
    result = flatten_dotnet_conf(raw)
    assert result == {"Database__AdminId": LeafType.STRING}


def test_dotnet_conf_duplicate_keys_keep_first_occurrence():
    raw = """\
# Oidc__Audience = topomojo-api
# Oidc__Audience = dev-api
"""
    result = flatten_dotnet_conf(raw)
    assert result == {"Oidc__Audience": LeafType.STRING}


def test_dotnet_conf_lines_without_equals_are_ignored():
    raw = """\
## Just a comment with no equals sign
# Oidc__Audience = topomojo-api
"""
    result = flatten_dotnet_conf(raw)
    assert result == {"Oidc__Audience": LeafType.STRING}
