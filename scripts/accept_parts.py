"""Explicit live acceptance request through the actual eight-tool MCP gateway.

Usage: python scripts/accept_parts.py --config CONFIG --operation parts_edit
       --arguments ARGS.json --report REPORT.json
No user source model is distributed with this script.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from multi_cad.backend import response_data


async def main(args):
    parameters = StdioServerParameters(command=sys.executable,
        args=['-m', 'multi_cad.gateway', '--config', str(Path(args.config).resolve())],
        env=dict(os.environ, PYTHONUTF8='1'))
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools = await session.list_tools()
            if len(tools.tools) != 8:
                raise ValueError('Gateway compatibility regression')
            await session.call_tool('capability_search', {'backend': 'project', 'query': 'parts'})
            await session.call_tool('operation_schema', {'backend': 'project', 'operation': args.operation})
            result = response_data(await session.call_tool('execute_operations', {'backend': 'project', 'calls': [
                {'operation': args.operation, 'arguments': json.loads(Path(args.arguments).read_text(encoding='utf-8-sig'))}]}))
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result['data'], ensure_ascii=False))
            passed = result['ok'] and result['data']['results'][0]['ok']
    return passed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('config', 'operation', 'arguments', 'report'):
        parser.add_argument('--'+name, required=True)
    raise SystemExit(0 if asyncio.run(main(parser.parse_args())) else 1)
