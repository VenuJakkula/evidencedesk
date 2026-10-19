"""Real stdio MCP discovery/invocation using the launcher's OIDC configuration."""
import asyncio
import os
import sys
from mcp import Client
from mcp.client.stdio import StdioServerParameters

async def main():
    if not os.getenv('EVIDENCEDESK_MCP_TOKEN'):
        raise SystemExit('Configure EVIDENCEDESK_MCP_TOKEN first')
    parameters = StdioServerParameters(command=sys.executable, args=['-m','app.mcp_server'], env=dict(os.environ))
    async with Client(parameters, read_timeout_seconds=20) as client:
        tools = (await client.list_tools()).tools
        print('Discovered: ' + ', '.join(tool.name for tool in tools))
        result = await client.call_tool('search_evidence', {'query':'encrypted','limit':5})
        if result.is_error:
            raise SystemExit('MCP search failed; check identity and current membership')
        # Do not print customer evidence or credentials in the demonstration.
        print('Authorized evidence matches: ' + str(len(result.structured_content['items'])))

if __name__ == '__main__':
    asyncio.run(main())
