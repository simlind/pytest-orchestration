import pytest


class DummyObject:

    def __init__(self):
        self.inc_value = 0
        self.dec_value = 0


@pytest.fixture
def dummy():
    return DummyObject()


@pytest.fixture
def dummy_adder(dummy):
    dummy.inc_value += 1
