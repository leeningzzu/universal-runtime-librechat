from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
from pathlib import Path

import typer
from rich import print

from universal_runtime.config import PROJECT_ROOT
from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.core.enums import PersistenceClass
from universal_runtime.models.deepseek import DeepSeekAgentFactory
from universal_runtime.models.profiles import load_model_profile
from universal_runtime.packs.registry import PackRegistry

app = typer.Typer(help='Local Universal Runtime v0.1')


@app.command()
def doctor() -> None:
    checks = {
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'deepseek_key_present': bool(os.getenv('DEEPSEEK_API_KEY')),
        'packs_found': len(PackRegistry(PROJECT_ROOT / 'packs').list_packs()),
        'mode': os.getenv('URT_MODE', 'shadow'),
    }
    try:
        import agent_framework  # noqa: F401
        checks['agent_framework'] = 'installed'
    except Exception as exc:
        checks['agent_framework'] = f'not available: {exc}'
    print_json = json.dumps(checks, ensure_ascii=False, indent=2)
    print(print_json)


@app.command('p08a-smoke')
def p08a_smoke() -> None:
    root = PROJECT_ROOT / 'artifacts' / 'smoke'
    store = ArtifactStore(root)
    text = '# P08 SMOKE\n\n原样持久化测试。\n'
    manifest = store.persist_exact_text(
        artifact_id='P08A_SMOKE',
        relative_path='P08A_SMOKE.md',
        text=text,
        job_id='SMOKE-P08A',
        persistence_class=PersistenceClass.WORKING,
    )
    print(manifest.model_dump_json(indent=2))


@app.command('deepseek-smoke')
def deepseek_smoke(profile: str = 'extract_fast') -> None:
    async def _run() -> None:
        model_profile = load_model_profile(profile, PROJECT_ROOT / 'config' / 'model_profiles.yaml')
        agent = DeepSeekAgentFactory(model_profile).create_agent(
            agent_id='deepseek-smoke',
            name='deepseek_smoke',
            instructions='只返回 JSON：{"status":"PASS","message":"连接成功"}',
        )
        response = await agent.run('执行连接测试。')
        print(response.text)
    asyncio.run(_run())


@app.command('list-packs')
def list_packs() -> None:
    print(json.dumps(PackRegistry(PROJECT_ROOT / 'packs').list_packs(), ensure_ascii=False, indent=2))


@app.command('web')
def web(host: str = '127.0.0.1', port: int = 8765) -> None:
    import uvicorn
    uvicorn.run('universal_runtime.webapp:app', host=host, port=port, reload=False)


if __name__ == '__main__':
    app()
