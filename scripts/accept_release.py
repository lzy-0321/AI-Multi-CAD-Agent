"""Run one explicitly requested CAD action through an installed gateway, in a fresh process."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from multi_cad.backend import response_data
import multi_cad


async def main(args):
    installation = Path(args.installation).resolve()
    entry = json.loads((installation / 'agent.json').read_text(encoding='utf-8'))['mcpServers']['multi_cad']
    project = Path(args.project).resolve()
    original = project / 'output/plate-v001.SLDPRT'
    before_hash = hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None
    output = installation / f'accept-{args.action}.json'
    with output.with_suffix('.log').open('w', encoding='utf-8') as log:
        async with stdio_client(StdioServerParameters(command=entry['command'], args=entry['args'], env=dict(os.environ)), errlog=log) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert len(tools.tools) == 8
                async def call(name, arguments):
                    value = response_data(await client.call_tool(name, arguments))
                    if not value['ok']:
                        raise RuntimeError(str(value))
                    return value['data']
                await call('capability_search', {'backend': 'solidworks', 'query': 'list documents', 'limit': 1})
                await call('operation_schema', {'backend': 'solidworks', 'operation': 'solidworks_list_documents'})
                query = {'backend': 'solidworks', 'calls': [{'operation': 'solidworks_list_documents', 'arguments': {}}]}
                before = await call('execute_operations', query)
                result = await call('plate_workflow', {'project': str(project), 'action': args.action,
                                                      'hole_diameter': 8 if args.action == 'edit' else 6})
                state = await call('project_state', {'project': str(project)})
                after = await call('execute_operations', query)
                before_docs = before['results'][0]['data']
                after_docs = after['results'][0]['data']
                assert before['results'][0]['ok'] and after['results'][0]['ok']
                assert before_docs == after_docs, 'Open documents or active document changed'
                assert state['last_validation']['passed'], state
                if before_hash:
                    assert hashlib.sha256(original.read_bytes()).hexdigest() == before_hash
                evidence = {'passed': True, 'action': args.action, 'package_location': str(multi_cad.__file__),
                    'gateway_tools': len(tools.tools), 'result': result, 'original_preserved': before_hash is not None,
                    'documents_preserved': True, 'open_document_count': len(before_docs.get('documents', [])),
                    'validation': state['last_validation'], 'versions': state['versions']}
                output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({'passed': True, 'action': args.action, 'report': str(output)}, ensure_ascii=False))


parser = argparse.ArgumentParser()
parser.add_argument('--installation', required=True)
parser.add_argument('--project', required=True)
parser.add_argument('--action', choices=['create', 'edit', 'verify'], required=True)
asyncio.run(main(parser.parse_args()))
