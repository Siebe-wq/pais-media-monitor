import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    return lambda name: json.loads((FIXTURES / name).read_text())


@pytest.fixture
def config_file(tmp_path):
    (tmp_path / "outlets.csv").write_text("domain,tier\nnos.nl,1\nnu.nl,2\n")
    (tmp_path / "config.toml").write_text('''
[topic]
name = "PauseAI"
description = "Test topic"
terms = ["PauseAI", "Pause AI"]

[[countries]]
code = "NL"
name = "Netherlands"
gdelt = "netherlands"

[[countries]]
code = "BE"
name = "Belgium"
gdelt = "belgium"

[[actions]]
date = 2026-08-15
label = "Protest"

[reach]
outlets_file = "outlets.csv"

[storage]
database = "test.db"
''')
    return tmp_path / "config.toml"
