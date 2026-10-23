"""Protocol-level gateway smoke test and reproducible context payload measurement."""
import asyncio
import json
import sys
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    configuration = str(Path(sys.argv[1]).resolve())
    output = Path(sys.argv[2]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    params = StdioServerParameters(command=sys.executable, args=['-m', 'multi_cad.gateway', '--config', configuration], env=dict(os.environ))
    with output.with_suffix('.log').open('w', encoding='utf-8') as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [t.name for t in tools.tools]
                assert 'capability_search' in names and 'plate_workflow' in names
                result = await session.call_tool('capability_search', {'backend':'solidworks', 'query':'extrusion', 'limit':3})
                assert not result.isError, result
                schema = await session.call_tool('operation_schema', {'backend':'solidworks', 'operation':'solidworks_create_extrusion'})
                assert not schema.isError, schema
                gateway_text = json.dumps([t.model_dump(mode='json') for t in tools.tools], ensure_ascii=False)
                downstream = json.loads((Path(__import__('multi_cad.config', fromlist=['home']).home())/'cache/solidworks-capabilities.json').read_text(encoding='utf-8'))
                all_text = json.dumps(downstream['tools'], ensure_ascii=False)
                selected = json.dumps(schema.model_dump(mode='json'), ensure_ascii=False)
                report = {'gateway_tools':names, 'upstream_tool_count':len(downstream['tools']),
                          'full_upstream_schema_chars':len(all_text), 'gateway_schema_chars':len(gateway_text),
                          'gateway_plus_one_schema_chars':len(gateway_text)+len(selected),
                          'character_reduction':1-(len(gateway_text)+len(selected))/len(all_text),
                          'measurement':'JSON characters; not tokenizer-specific token counts'}
                output.write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(report))

asyncio.run(main())
