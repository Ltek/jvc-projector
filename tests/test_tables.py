"""Static checks: translations, icons, command tables, README, services."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from custom_components.jvc_projector_ha import select, sensor, switch
from custom_components.jvc_projector_ha.jvcprojector.command import JvcCommand

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "jvc_projector_ha"
EN = json.loads((INTEGRATION / "translations" / "en.json").read_text())
STRINGS = json.loads((INTEGRATION / "strings.json").read_text())
ICONS = json.loads((INTEGRATION / "icons.json").read_text())
KEY_RE = re.compile(r"^(?![-_])[a-z0-9-_]+(?<![-_])$")


def _enum_descriptions():
    for d in sensor.JVC_SENSORS:
        if d.options:
            yield "sensor", d
    for d in select.JVC_SELECTS:
        yield "select", d


def _all_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if path.endswith(".state"):
                yield k, path
            yield from _all_keys(v, f"{path}.{k}")


def test_strings_json_matches_en_json():
    assert STRINGS == EN


def test_every_option_has_a_translation():
    for platform, d in _enum_descriptions():
        states = EN["entity"][platform][d.translation_key]["state"]
        missing = [o for o in d.options if o not in states]
        assert not missing, f"{platform}.{d.translation_key}: {missing}"
        extra = [s for s in states if s not in d.options]
        assert not extra, f"{platform}.{d.translation_key} stale: {extra}"


def test_every_entity_has_a_name():
    descs = [*sensor.JVC_SENSORS, sensor.HOURS_SENSOR]
    for d in descs:
        assert EN["entity"]["sensor"][d.translation_key]["name"]
    for d in select.JVC_SELECTS:
        assert EN["entity"]["select"][d.translation_key]["name"]
    for d in switch.JVC_SWITCHES:
        assert EN["entity"]["switch"][d.translation_key]["name"]


def test_state_keys_are_valid_for_hassfest():
    for source in (EN, ICONS):
        for key, path in _all_keys(source["entity"]):
            assert KEY_RE.match(key), f"{path}: {key!r}"
    for _platform, d in _enum_descriptions():
        for option in d.options:
            assert KEY_RE.match(option), f"{d.key}: {option!r}"


def _formatter_reverse(pattern: str) -> dict[str, str]:
    fmt = JvcCommand.formatters[pattern]
    if isinstance(fmt, dict):
        return {v: k for k, v in fmt.items()}
    return {v: f"{i:X}" for i, v in enumerate(fmt) if v is not None}


def test_select_codes_match_command_table():
    patterns = {
        "PMPM": "PMPM(..)",
        "PMDC": "PMDC(.)",
        "input": "(?:IP|IFIN)(.)",
        "INML": "INML(.)",
        "INVS": "INVS(.)",
        "PMHP": "PMHP(.)",
        "PMHL": "PMHL(.)",
    }
    for d in select.JVC_SELECTS:
        reverse = _formatter_reverse(patterns[d.key])
        for option, code in d.code_map.items():
            assert reverse.get(option) == code, f"{d.key} {option}: {code}"


def test_formatter_output_matches_sensor_options():
    cmd = JvcCommand("IFCM", True)
    cmd.response = "8"
    assert cmd.response == "bt2020_cl"
    cmd = JvcCommand("IFIS", True)
    cmd.response = "0B"
    assert cmd.response == "no_signal"


def test_no_undeclared_services():
    """services.yaml must only describe services the integration registers."""
    assert not (INTEGRATION / "services.yaml").exists()
    for py in INTEGRATION.rglob("*.py"):
        assert "async_register" not in py.read_text(), py


def test_no_aiodns_dependency():
    for py in INTEGRATION.rglob("*.py"):
        assert "import aiodns" not in py.read_text(), py
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert manifest["requirements"] == []


def test_readme_password_example_is_sha256():
    readme = (ROOT / "README.md").read_text()
    assert "MD5" not in readme
    m = re.search(r'"([0-9a-f]{64})"', readme)
    assert m, "README should show an example SHA-256 hash"
    assert m[1] == sha256(b"MyPasswordJVCKWPJ").hexdigest()


def test_version_is_consistent():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    version = manifest["version"]
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+", version)
    assert f"## v{version}" in (ROOT / "CHANGELOG.md").read_text()
    assert f"**v{version}**" in (ROOT / "README.md").read_text()
    assert f'version = "{version}"' in (ROOT / "pyproject.toml").read_text()


def test_installation_mode_options_per_model():
    assert len(select.installation_mode_options("ILAFPJ -- D8A2")) == 5  # NZ500
    assert len(select.installation_mode_options("ILAFPJ -- D8A1")) == 5  # NZ700
    assert len(select.installation_mode_options("ILAFPJ -- B8A1")) == 10  # NZ900
    assert len(select.installation_mode_options(None)) == 10
