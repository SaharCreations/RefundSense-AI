from pathlib import Path

import pytest

from refundguard.corpus import load_corpus


@pytest.fixture
def data_dir():
    return Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def chunks(data_dir):
    return load_corpus(data_dir / "policies")
