import sys
import types

import pytest

from universal_runtime.core.models import ModelProfile
from universal_runtime.models.deepseek import DeepSeekAgentFactory


class _FakeAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture
def fake_agent_framework(monkeypatch):
    agent_framework = types.ModuleType('agent_framework')
    agent_framework.Agent = _FakeAgent
    openai_module = types.ModuleType('agent_framework.openai')
    openai_module.OpenAIChatCompletionClient = _FakeClient
    monkeypatch.setitem(sys.modules, 'agent_framework', agent_framework)
    monkeypatch.setitem(sys.modules, 'agent_framework.openai', openai_module)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'deterministic-test-key')


@pytest.mark.parametrize(
    ('thinking', 'reasoning_effort'),
    [('disabled', 'low'), ('enabled', 'high')],
)
def test_deepseek_thinking_is_mapped_to_extra_body(
    fake_agent_framework, thinking, reasoning_effort
):
    profile = ModelProfile(
        profile_id='test',
        model='test-model',
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        max_tokens=1234,
    )

    agent = DeepSeekAgentFactory(profile).create_agent(
        agent_id='agent', name='name', instructions='instructions'
    )
    options = agent.kwargs['default_options']

    assert 'thinking' not in options
    assert options['extra_body'] == {'thinking': {'type': thinking}}
    assert options['reasoning_effort'] == reasoning_effort
    assert options['max_tokens'] == 1234
    assert options['response_format'] == {'type': 'json_object'}

