import pytest

from tb_swarm.stub_server import StubServer, StubState

STUB_KEY = "stub-key-not-a-secret"


@pytest.fixture
def stub():
    server = StubServer(StubState(api_key=STUB_KEY)).start()
    yield server
    server.stop()
