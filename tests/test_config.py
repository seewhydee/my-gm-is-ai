# My GM is AI — an AI-driven Game Master for tabletop RPG adventures
# Copyright (C) 2026  Chong Yidong <cyd@stupidchicken.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import stat
from pathlib import Path


from mgmai.config import (
    AppConfig,
    Credentials,
    get_config_dir,
    get_config_file,
    get_credentials_file,
    get_saves_dir,
    get_autosave_path,
    load_app_config,
    save_app_config,
    load_credentials,
    save_credentials,
    resolve_api_key,
)


class TestPaths:
    def test_get_config_dir_override(self):
        d = get_config_dir("/custom/path")
        assert d == Path("/custom/path")

    def test_get_config_dir_default(self):
        d = get_config_dir()
        assert d.name == "mgmai"

    def test_get_config_file(self, tmp_path):
        p = get_config_file(tmp_path)
        assert p == tmp_path / "config.json"

    def test_get_credentials_file(self, tmp_path):
        p = get_credentials_file(tmp_path)
        assert p == tmp_path / "credentials.json"

    def test_get_saves_dir_default(self, tmp_path):
        d = get_saves_dir(config_dir=tmp_path)
        assert d == tmp_path / "saves"

    def test_get_saves_dir_scoped(self, tmp_path):
        d = get_saves_dir("bag-of-holding", config_dir=tmp_path)
        assert d == tmp_path / "saves" / "bag-of-holding"

    def test_get_autosave_path(self, tmp_path):
        p = get_autosave_path("bag-of-holding", config_dir=tmp_path)
        assert p == tmp_path / "saves" / "bag-of-holding" / "autosave.json"


class TestAppConfig:
    def test_defaults(self):
        c = AppConfig()
        assert c.model_name == "deepseek-v4-flash"
        assert c.base_url is None
        assert c.ruling_temperature is None
        assert c.prose_temperature is None

    def test_to_dict_omits_nones(self):
        c = AppConfig(model_name="gpt-4o")
        d = c.to_dict()
        assert "base_url" not in d
        assert "ruling_temperature" not in d
        assert d["model_name"] == "gpt-4o"

    def test_to_dict_includes_set_fields(self):
        c = AppConfig(
            model_name="test",
            base_url="https://example.com",
            ruling_temperature=0.5,
            prose_temperature=0.8,
        )
        d = c.to_dict()
        assert d["base_url"] == "https://example.com"
        assert d["ruling_temperature"] == 0.5
        assert d["prose_temperature"] == 0.8

    def test_from_dict_partial(self):
        c = AppConfig.from_dict({"model_name": "test"})
        assert c.model_name == "test"
        assert c.base_url is None

    def test_from_dict_empty(self):
        c = AppConfig.from_dict({})
        assert c.model_name == "deepseek-v4-flash"

    def test_roundtrip(self, tmp_path):
        c = AppConfig(model_name="gpt-4o", base_url="https://api.openai.com/v1")
        save_app_config(c, tmp_path)
        loaded = load_app_config(tmp_path)
        assert loaded.model_name == "gpt-4o"
        assert loaded.base_url == "https://api.openai.com/v1"

    def test_load_missing_file_returns_default(self, tmp_path):
        c = load_app_config(tmp_path)
        assert c.model_name == "deepseek-v4-flash"

    def test_load_corrupt_file_returns_default(self, tmp_path):
        path = get_config_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json")
        c = load_app_config(tmp_path)
        assert c.model_name == "deepseek-v4-flash"

    def test_adventure_path_persisted(self, tmp_path):
        c = AppConfig(adventure_path="/some/adventure")
        save_app_config(c, tmp_path)
        loaded = load_app_config(tmp_path)
        assert loaded.adventure_path == "/some/adventure"


class TestCredentials:
    def test_default_empty(self):
        c = Credentials()
        assert c.api_keys == {}

    def test_to_dict(self):
        c = Credentials(api_keys={"deepseek": "sk-abc123"})
        assert c.to_dict() == {"api_keys": {"deepseek": "sk-abc123"}}

    def test_to_dict_empty(self):
        c = Credentials()
        assert c.to_dict() == {}

    def test_roundtrip(self, tmp_path):
        c = Credentials(api_keys={"deepseek": "sk-secret"})
        save_credentials(c, tmp_path)
        loaded = load_credentials(tmp_path)
        assert loaded.api_keys == {"deepseek": "sk-secret"}

    def test_load_missing_file_returns_empty(self, tmp_path):
        c = load_credentials(tmp_path)
        assert c.api_keys == {}

    def test_file_has_restrictive_permissions(self, tmp_path):
        c = Credentials(api_keys={"deepseek": "sk-secret"})
        save_credentials(c, tmp_path)
        path = get_credentials_file(tmp_path)
        mode = path.stat().st_mode
        expected = stat.S_IRUSR | stat.S_IWUSR
        assert mode & 0o777 == expected

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        path = get_credentials_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json")
        c = load_credentials(tmp_path)
        assert c.api_keys == {}


class TestResolveApiKey:
    def test_cli_arg_wins(self):
        creds = Credentials(api_keys={"deepseek": "from-file"})
        assert resolve_api_key(cli_arg="cli", env_var="env",
                               credentials=creds, provider="deepseek") == "cli"

    def test_override_key_wins_over_env(self):
        creds = Credentials(api_keys={"deepseek": "from-file"})
        assert resolve_api_key(env_var="env", credentials=creds,
                               provider="deepseek",
                               override_key="override") == "override"

    def test_env_wins_over_file(self):
        creds = Credentials(api_keys={"deepseek": "from-file"})
        assert resolve_api_key(env_var="env", credentials=creds,
                               provider="deepseek") == "env"

    def test_provider_key_from_credentials(self):
        creds = Credentials(api_keys={"deepseek": "from-file"})
        assert resolve_api_key(credentials=creds, provider="deepseek") == "from-file"

    def test_missing_provider_returns_empty(self):
        creds = Credentials(api_keys={"deepseek": "from-file"})
        assert resolve_api_key(credentials=creds, provider="moonshot") == ""

    def test_no_provider_returns_empty(self):
        creds = Credentials(api_keys={"deepseek": "from-file"})
        assert resolve_api_key(credentials=creds) == ""

    def test_all_empty_returns_empty(self):
        assert resolve_api_key() == ""

    def test_empty_strings_ignored(self):
        creds = Credentials(api_keys={"deepseek": "from-file"})
        assert resolve_api_key(cli_arg="", env_var="", credentials=creds,
                               provider="deepseek") == "from-file"
