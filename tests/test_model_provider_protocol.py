from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.model_provider import ModelProvider


def test_fake_model_provider_satisfies_the_protocol():
    provider: ModelProvider = FakeModelProvider()
    assert hasattr(provider, "plan")
    assert hasattr(provider, "code")
    assert hasattr(provider, "review")


def test_protocol_is_structural_not_nominal():
    class Anything:
        def plan(self, context: dict) -> dict:
            return {}

        def code(self, context: dict) -> dict:
            return {}

        def review(self, context: dict) -> dict:
            return {}

    instance: ModelProvider = Anything()
    assert instance.plan({}) == {}
