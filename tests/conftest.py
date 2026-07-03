import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.digital_products import manual_catalog


@pytest.fixture(autouse=True)
def _fresh_public_catalog_nodes_cache():
    """The website_manual tree cache is process-global; never leak it between tests."""
    manual_catalog._public_nodes_cache.update({"at": 0.0, "nodes": None, "task": None})
    yield
    manual_catalog._public_nodes_cache.update({"at": 0.0, "nodes": None, "task": None})
