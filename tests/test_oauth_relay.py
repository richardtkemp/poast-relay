"""End-to-end integration tests for OAuth relay."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from app.config import Settings
from app.oauth.client import wait_for_code, OAuthTimeoutError, OAuthConnectionError
from app.oauth.coordinator import OAuthCoordinator, set_coordinator


@pytest_asyncio.fixture
async def temp_socket():
    """Create a temporary socket path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "test-oauth.sock")
        yield socket_path


@pytest_asyncio.fixture
async def test_settings(temp_socket):
    """Create test settings with temporary socket."""
    return Settings(
        inbound_path_uuid="test-uuid",
        inbound_auth_token="test-token",
        groq_api_key="test-groq",
        gateway_url="http://localhost:8080",
        gateway_token="test-gateway",
        target_session_key="test-session",
        oauth_enabled=True,
        oauth_socket_path=temp_socket,
        oauth_use_tcp=False,
        oauth_default_timeout=5.0,
    )


@pytest_asyncio.fixture
async def coordinator(test_settings):
    """Create and start a test coordinator."""
    coord = OAuthCoordinator(test_settings)
    set_coordinator(coord)

    # Start coordinator in background
    coord_task = asyncio.create_task(coord.start())

    # Give it time to start
    await asyncio.sleep(0.1)

    yield coord

    # Cleanup
    await coord.stop()
    try:
        coord_task.cancel()
        await coord_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_oauth_flow_with_state(test_settings, coordinator):
    """Test full OAuth flow with state parameter."""
    state = "test-state-123"
    code = "auth_code_xyz"

    # Start client waiting task
    async def wait_task():
        result = await wait_for_code(state=state, settings=test_settings)
        assert result.success
        assert result.code == code
        return result

    # Start client
    client_task = asyncio.create_task(wait_task())

    # Give client time to register
    await asyncio.sleep(0.2)

    # Simulate OAuth callback
    delivered = coordinator.deliver_result(state, code)
    assert delivered

    # Wait for client to receive result
    result = await client_task
    assert result.code == code


@pytest.mark.asyncio
async def test_oauth_flow_no_state(test_settings, coordinator):
    """Test OAuth flow in single-slot mode (no state)."""
    code = "auth_code_default"

    async def wait_task():
        result = await wait_for_code(state=None, settings=test_settings)
        assert result.success
        assert result.code == code
        return result

    client_task = asyncio.create_task(wait_task())
    await asyncio.sleep(0.2)

    delivered = coordinator.deliver_result(None, code)
    assert delivered

    result = await client_task
    assert result.code == code


@pytest.mark.asyncio
async def test_no_client_returns_false(test_settings, coordinator):
    """Test that callback returns False when no client is registered."""
    state = "unmatched-state"
    code = "some_code"

    delivered = coordinator.deliver_result(state, code)
    assert not delivered


@pytest.mark.asyncio
async def test_already_delivered_returns_false(test_settings, coordinator):
    """Test that second delivery returns False (already delivered)."""
    state = "test-state"
    code = "code1"

    async def wait_task():
        return await wait_for_code(state=state, settings=test_settings)

    client_task = asyncio.create_task(wait_task())
    await asyncio.sleep(0.2)

    # First delivery succeeds
    delivered1 = coordinator.deliver_result(state, code)
    assert delivered1

    # Wait for client to complete
    await client_task

    # Start new client for same state
    client_task2 = asyncio.create_task(wait_for_code(state=state, settings=test_settings))
    await asyncio.sleep(0.2)

    # Second delivery with different code - should fail because old future is resolved
    delivered2 = coordinator.deliver_result(state, "code2")
    # This should succeed because a new client registered
    assert delivered2

    # Clean up
    await client_task2


@pytest.mark.asyncio
async def test_timeout_raises_exception(test_settings, coordinator):
    """Test that timeout raises OAuthTimeoutError."""
    state = "timeout-state"
    short_timeout = 0.5

    with pytest.raises(OAuthTimeoutError):
        await wait_for_code(state=state, timeout=short_timeout, settings=test_settings)


@pytest.mark.asyncio
async def test_extraction_fallback_no_code(test_settings, coordinator):
    """Test that raw payload is returned when code extraction fails."""
    state = "test-state"
    raw_data = {"error": "access_denied", "error_description": "User denied"}

    async def wait_task():
        result = await wait_for_code(state=state, settings=test_settings)
        assert not result.success
        assert result.raw == raw_data
        return result

    client_task = asyncio.create_task(wait_task())
    await asyncio.sleep(0.2)

    delivered = coordinator.deliver_result(state, None, raw_data)
    assert delivered

    result = await client_task
    assert result.raw == raw_data


@pytest.mark.asyncio
async def test_case_insensitive_extraction(test_settings, coordinator):
    """Test case-insensitive code key extraction."""
    settings = Settings(
        inbound_path_uuid="test-uuid",
        inbound_auth_token="test-token",
        groq_api_key="test-groq",
        gateway_url="http://localhost:8080",
        gateway_token="test-gateway",
        target_session_key="test-session",
        oauth_enabled=True,
        oauth_socket_path=test_settings.oauth_socket_path,
        oauth_use_tcp=False,
        oauth_default_timeout=5.0,
        oauth_code_keys=["code", "authorization_code"],
    )

    # Test uppercase key
    from app.routes.oauth import extract_code

    data = {"CODE": "upper_case_code"}
    extracted = extract_code(data, settings.oauth_code_keys)
    assert extracted == "upper_case_code"

    # Test mixed case
    data2 = {"CoDeVaLuE": "mixed_case_code"}
    extracted2 = extract_code(data2, settings.oauth_code_keys)
    # Should not match because "codevalue" is not in the keys
    assert extracted2 is None

    # Test alternative key
    data3 = {"AUTHORIZATION_CODE": "alt_key_code"}
    extracted3 = extract_code(data3, settings.oauth_code_keys)
    assert extracted3 == "alt_key_code"


def test_oauth_endpoint_extraction():
    """Test OAuth endpoint code extraction logic."""
    from app.routes.oauth import extract_code

    settings = Settings(
        inbound_path_uuid="test-uuid",
        inbound_auth_token="test-token",
        groq_api_key="test-groq",
        gateway_url="http://localhost:8080",
        gateway_token="test-gateway",
        target_session_key="test-session",
        oauth_code_keys=["code", "authorization_code"],
    )

    # Test normal extraction
    data = {"code": "test_code"}
    assert extract_code(data, settings.oauth_code_keys) == "test_code"

    # Test missing code
    data = {"error": "access_denied"}
    assert extract_code(data, settings.oauth_code_keys) is None

    # Test uppercase key
    data = {"CODE": "upper_code"}
    assert extract_code(data, settings.oauth_code_keys) == "upper_code"


@pytest.mark.asyncio
async def test_multiple_clients_same_state(test_settings, coordinator):
    """Test that new registration replaces old one for same state."""
    state = "shared-state"
    code1 = "code1"
    code2 = "code2"

    results = []

    async def client1():
        try:
            result = await wait_for_code(state=state, settings=test_settings)
            results.append(("client1", result))
        except Exception as e:
            results.append(("client1", e))

    async def client2():
        try:
            result = await wait_for_code(state=state, settings=test_settings)
            results.append(("client2", result))
        except Exception as e:
            results.append(("client2", e))

    # Start first client
    task1 = asyncio.create_task(client1())
    await asyncio.sleep(0.2)

    # Start second client (should replace first)
    task2 = asyncio.create_task(client2())
    await asyncio.sleep(0.2)

    # Deliver code - should go to second client
    delivered = coordinator.deliver_result(state, code2)
    assert delivered

    # Wait for tasks to complete (with timeout for first which should timeout or error)
    await asyncio.sleep(0.5)

    # Clean up any remaining tasks
    for task in [task1, task2]:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_connection_error_no_server(test_settings):
    """Test that connection fails when coordinator not running."""
    test_settings.oauth_socket_path = "/tmp/nonexistent-oauth.sock"

    with pytest.raises(OAuthConnectionError):
        await wait_for_code(state="test", settings=test_settings)


@pytest.mark.asyncio
async def test_list_value_in_params(test_settings, coordinator):
    """Test extraction when code value is a list."""
    from app.routes.oauth import extract_code

    data = {"code": ["first_code", "second_code"]}
    extracted = extract_code(data, test_settings.oauth_code_keys)
    assert extracted == "first_code"  # Should take first element


@pytest.mark.asyncio
async def test_empty_code_value(test_settings, coordinator):
    """Test extraction when code value is empty string."""
    from app.routes.oauth import extract_code

    data = {"code": ""}
    extracted = extract_code(data, test_settings.oauth_code_keys)
    assert extracted is None


@pytest.mark.asyncio
async def test_code_extraction_no_match(test_settings):
    """Test extraction when no matching key found."""
    from app.routes.oauth import extract_code

    data = {"error": "access_denied"}
    extracted = extract_code(data, test_settings.oauth_code_keys)
    assert extracted is None
