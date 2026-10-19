import asyncio
import os
import sys
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from app.mcp_server import build_server
from test_access import environment, approved


def run(coroutine):
    return asyncio.run(coroutine)


def test_protocol_discovery_reads_cas_and_validation(environment):
    store, evidence, questionnaires, token, scope = environment
    source, questionnaire, item = approved(environment)
    async def scenario():
        async with Client(build_server(store, token('author'), 'a')) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {'search_evidence','get_questionnaire','get_questionnaire_items','submit_draft'}
            result = await client.call_tool('search_evidence', {'query':'encrypted'})
            assert not result.is_error, result
            assert result.structured_content['items'][0]['version_id'] == source['current_version']
            result = await client.call_tool('get_questionnaire', {'questionnaire_id':questionnaire['id']})
            assert not result.is_error
            result = await client.call_tool('get_questionnaire_items', {'questionnaire_id':questionnaire['id']})
            assert not result.is_error
            result = await client.call_tool('submit_draft', {'item_id':item['id'],'text':'Proposed answer','expected_revision':1})
            assert not result.is_error
            current = questionnaires.item(scope('author'), item['id'])
            assert current['current_revision'] == 2 and not current['answer']['approval']
            assert (await client.call_tool('submit_draft', {'item_id':item['id'],'text':'stale','expected_revision':1})).is_error
            for args in [{'query':''}, {'query':'x','limit':51}, {'query':'x','limit':True}]:
                assert (await client.call_tool('search_evidence',args)).is_error
            scoped = await client.call_tool('search_evidence', {'query':'encrypted','tenant':'b'})
            assert scoped.structured_content['items'][0]['source_id'] == source['id']
            assert (await client.call_tool('get_questionnaire', {'questionnaire_id':'missing'})).is_error
            assert (await client.call_tool('approve', {})).is_error
    run(scenario())


@pytest.mark.parametrize('change',['acl','revoke','delete','update','expire','reviewer'])
def test_protocol_evidence_lifecycle(environment, change):
    store,evidence,questionnaires,token,scope = environment
    source,questionnaire,item = approved(environment)
    async def scenario():
        async with Client(build_server(store,token('author'),'a')) as client:
            assert (await client.call_tool('search_evidence',{'query':'encrypted'})).structured_content['items']
            if change == 'acl': evidence.acl(scope(),source['id'],'author',remove=True)
            elif change == 'revoke': evidence.revoke(scope(),source['id'])
            elif change == 'delete': evidence.revoke(scope(),source['id'],delete=True)
            elif change == 'update': evidence.version(scope('author'),source['id'],source['current_version'],'Updated policy','2','2099-01-01')
            elif change == 'reviewer': evidence.membership(scope(),'reviewer',[],False)
            else:
                # The clock changes; immutable payloads are never edited.
                from unittest.mock import patch
                from datetime import date
                with patch('app.evidence.date') as clock:
                    clock.today.return_value = date(2100,1,1)
                    assert not (await client.call_tool('search_evidence',{'query':'encrypted'})).structured_content['items']
                return
            assert not (await client.call_tool('search_evidence',{'query':'encrypted'})).structured_content['items']
    run(scenario())


def test_protocol_isolation_revocation_and_expired_token(environment):
    store,evidence,questionnaires,token,scope = environment
    source,questionnaire,item = approved(environment)
    async def scenario():
        async with Client(build_server(store,token('outsider'),'a')) as client:
            assert not (await client.call_tool('search_evidence',{'query':'encrypted'})).structured_content['items']
            result = await client.call_tool('get_questionnaire_items',{'questionnaire_id':questionnaire['id']})
            assert 'AES-256' not in str(result.structured_content)
            evidence.membership(scope(),'outsider',[],False)
            assert (await client.call_tool('get_questionnaire',{'questionnaire_id':questionnaire['id']})).is_error
        async with Client(build_server(store,token('other'),'b')) as client:
            assert (await client.call_tool('get_questionnaire',{'questionnaire_id':questionnaire['id']})).is_error
        async with Client(build_server(store,token('reviewer'),'a')) as client:
            assert (await client.call_tool('submit_draft',{'item_id':item['id'],'text':'x','expected_revision':1})).is_error
        async with Client(build_server(store,token(exp=0),'a')) as client:
            assert (await client.call_tool('search_evidence',{'query':'encrypted'})).is_error
    run(scenario())


def test_real_stdio_client(environment):
    store,evidence,questionnaires,token,scope = environment
    approved(environment)
    env = dict(os.environ, EVIDENCEDESK_MCP_TOKEN=token('author'), EVIDENCEDESK_TENANT='a')
    async def scenario():
        async with Client(StdioServerParameters(command=sys.executable,args=['-m','app.mcp_server'],env=env),read_timeout_seconds=15) as client:
            assert len((await client.list_tools()).tools) == 4
            result = await client.call_tool('search_evidence',{'query':'encrypted'})
            assert not result.is_error and result.structured_content['items']
    run(scenario())


def test_pending_and_unavailable_storage(environment, monkeypatch):
    store,evidence,questionnaires,token,scope = environment
    evidence.create(scope('author'),'Pending','Customer data encrypted.','1','2099-01-01')
    async def scenario():
        async with Client(build_server(store,token('author'),'a')) as client:
            assert not (await client.call_tool('search_evidence',{'query':'encrypted'})).structured_content['items']
            def unavailable():
                raise RuntimeError('sensitive database path')
            monkeypatch.setattr(store,'connect',unavailable)
            result = await client.call_tool('search_evidence',{'query':'encrypted'})
            assert result.is_error and 'sensitive database path' not in str(result)
    run(scenario())


def test_local_mode_cannot_bypass_identity(environment, monkeypatch):
    store,_,_,token,_ = environment
    monkeypatch.setenv('EVIDENCEDESK_AUTH_MODE','local')
    async def scenario():
        async with Client(build_server(store,token(),'a')) as client:
            assert (await client.call_tool('search_evidence',{'query':'encrypted'})).is_error
    run(scenario())
