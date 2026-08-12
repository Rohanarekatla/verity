import sys
import pytest
from verity.orchestrator.rpc_client import RPCClient


@pytest.mark.asyncio
async def test_rpc_client_successful_request():
    mock_script = (
        "import sys, json; "
        "line = sys.stdin.readline(); "
        "req = json.loads(line); "
        "res = {'jsonrpc': '2.0', 'id': req['id'], 'result': {'status': 'ok', 'url': req['params']['url']}}; "
        "print(json.dumps(res)); "
        "sys.stdout.flush()"
    )

    client = RPCClient([sys.executable, "-c", mock_script])
    await client.start()

    try:
        result = await client.send_request("render", {"url": "https://example.com"})
        assert result == {"status": "ok", "url": "https://example.com"}
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_rpc_client_error_response():
    mock_script = (
        "import sys, json; "
        "line = sys.stdin.readline(); "
        "req = json.loads(line); "
        "res = {'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -32601, 'message': 'Method not found'}}; "
        "print(json.dumps(res)); "
        "sys.stdout.flush()"
    )

    client = RPCClient([sys.executable, "-c", mock_script])
    await client.start()

    try:
        with pytest.raises(RuntimeError) as exc_info:
            await client.send_request("unknown_method", {})
        assert "Method not found" in str(exc_info.value)
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_rpc_client_timeout():
    mock_script = "import time; time.sleep(10)"

    client = RPCClient([sys.executable, "-c", mock_script], default_timeout=0.2)
    await client.start()

    try:
        with pytest.raises(TimeoutError):
            await client.send_request("render", {"url": "https://example.com"})
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_rpc_client_invalid_command():
    client = RPCClient(["non_existent_binary_12345"])
    with pytest.raises(FileNotFoundError):
        await client.start()