import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src.message_bus import InMemoryMessageBus


@pytest.fixture
def bus():
    return InMemoryMessageBus()
