"""
Health check tests.
Verifies that all required services are healthy and accessible.
"""

import pytest
from lib.health_checker import HealthStatus


pytestmark = pytest.mark.asyncio


@pytest.mark.health
async def test_all_services_healthy(health_checker):
    """Verify all required services reach healthy state."""
    statuses = await health_checker.check_all_services()
    
    # Check that we have statuses for expected services
    assert 'frontend' in statuses, "Frontend service status not found"
    assert 'backend' in statuses, "Backend service status not found"
    
    # Check each service is healthy
    for service_name, status in statuses.items():
        assert status == HealthStatus.HEALTHY, \
            f"{service_name} is not healthy: {status} " \
            f"(error: {health_checker.get_error(service_name)})"


@pytest.mark.health
async def test_frontend_service_healthy(health_checker):
    """Verify frontend service is accessible and healthy."""
    status = await health_checker.check_service("frontend")
    assert status is True, \
        f"Frontend service is not healthy. Error: {health_checker.get_error('frontend')}"


@pytest.mark.health
async def test_backend_service_healthy(health_checker):
    """Verify backend API service is accessible and healthy."""
    status = await health_checker.check_service("backend")
    assert status is True, \
        f"Backend service is not healthy. Error: {health_checker.get_error('backend')}"


@pytest.mark.health
async def test_database_service_healthy(health_checker):
    """Verify database service is accessible and healthy."""
    status = await health_checker.check_service("database")
    assert status is True, \
        f"Database service is not healthy. Error: {health_checker.get_error('database')}"


@pytest.mark.health
async def test_service_status_property(health_checker):
    """Verify service_status property returns current statuses."""
    # First check all services
    await health_checker.check_all_services()
    
    # Then verify property access
    statuses = health_checker.service_statuses
    assert isinstance(statuses, dict), "service_statuses should return a dictionary"
    assert len(statuses) > 0, "service_statuses should not be empty"


@pytest.mark.health
async def test_error_tracking(health_checker):
    """Verify error tracking for failed health checks."""
    await health_checker.check_all_services()
    
    # For each service, either it's healthy or has an error message
    for service_name, status in health_checker.service_statuses.items():
        if status != HealthStatus.HEALTHY:
            error = health_checker.get_error(service_name)
            assert error is not None, \
                f"Service {service_name} is not healthy but has no error message"
