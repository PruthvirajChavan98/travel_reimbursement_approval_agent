import pytest

from app import config
from app.decision import load_prior_claims


@pytest.fixture(scope="session")
def policy():
    return config.load_policy()


@pytest.fixture(scope="session")
def prior():
    return load_prior_claims()


@pytest.fixture
def load_sample():
    from app.models import Claim

    def _load(name: str) -> Claim:
        return Claim.model_validate_json((config.CLAIMS_DIR / name).read_text())

    return _load
