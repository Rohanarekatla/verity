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

@pytest.mark.asyncio
async def test_rpc_client_handles_frame_larger_than_asyncio_default_limit():
    """
    A real runAxe response is far bigger than asyncio's 64 KiB StreamReader
    default -- a page with ~67 violations produces roughly 370 KB in one
    frame. Before the stream limit was raised, readline() raised ValueError,
    the reader task died silently, and every caller blocked until its own
    timeout with a misleading "timed out" message.

    200 KB here is comfortably over the 64 KiB default and well under the
    configured cap, so this fails loudly if the limit is ever reverted.
    """
    payload_size = 200_000
    mock_script = (
        "import sys, json; "
        "line = sys.stdin.readline(); "
        "req = json.loads(line); "
        f"res = {{'jsonrpc': '2.0', 'id': req['id'], 'result': {{'blob': 'A' * {payload_size}}}}}; "
        "sys.stdout.write(json.dumps(res) + '\\n'); "
        "sys.stdout.flush()"
    )

    client = RPCClient(command=[sys.executable, "-c", mock_script], default_timeout=10.0)
    await client.start()
    try:
        result = await client.send_request("runAxe", {"artifactId": "big"})
        assert len(result["blob"]) == payload_size
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_rpc_client_surfaces_worker_death_instead_of_hanging():
    """
    If the worker exits without answering, the caller must get a real error
    immediately rather than waiting out its timeout. A hang is worse than a
    failure: it hides the cause.
    """
    # Reads the request, then exits without writing a response.
    mock_script = "import sys; sys.stdin.readline()"

    client = RPCClient(command=[sys.executable, "-c", mock_script], default_timeout=30.0)
    await client.start()
    try:
        with pytest.raises(RuntimeError, match="closed stdout"):
            await client.send_request("render", {"url": "https://example.com"})
    finally:
        await client.stop()
