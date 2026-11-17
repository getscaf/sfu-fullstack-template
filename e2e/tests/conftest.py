"""
Pytest configuration and fixtures.
Provides shared fixtures for all E2E tests.
"""

import os
import sys
import pytest
import asyncio
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.health_checker import HealthChecker, HealthStatus
from lib.fixtures import load_test_data, get_database_config


# Configure asyncio for pytest
@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


@pytest.fixture(scope="session")
def config_dir(project_root):
    """Get the configuration directory."""
    return project_root / "e2e" / "config"


@pytest.fixture(scope="session")
def test_dir(project_root):
    """Get the tests directory."""
    return project_root / "e2e" / "tests"


@pytest.fixture(scope="session")
def reports_dir(project_root):
    """Get the reports directory."""
    reports = project_root / "e2e" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    return reports


@pytest.fixture(scope="session")
async def health_checker(config_dir):
    """Create a health checker instance."""
    health_checks_config = config_dir / "health-checks.yaml"
    if not health_checks_config.exists():
        pytest.skip("health-checks.yaml not found")
    
    return HealthChecker(str(health_checks_config))


@pytest.fixture(scope="session")
def test_data(config_dir):
    """Load test data."""
    test_data_config = config_dir / "test-data.yaml"
    if not test_data_config.exists():
        pytest.skip("test-data.yaml not found")
    
    return load_test_data(str(test_data_config))


@pytest.fixture(scope="function")
def frontend_url():
    """Get frontend URL from environment or default."""
    return os.getenv("FRONTEND_URL", "http://frontend:3000")


@pytest.fixture(scope="function")
def backend_url():
    """Get backend URL from environment or default."""
    return os.getenv("BACKEND_URL", "http://backend:8000")


@pytest.fixture(scope="function")
def database_config(test_data):
    """Get database configuration from test data."""
    return get_database_config(test_data)


@pytest.fixture(scope="function")
def db_password():
    """Get database password from environment."""
    return os.getenv("DB_PASSWORD", "postgres")


# Pytest configuration
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "health: mark test as a health check"
    )
    config.addinivalue_line(
        "markers", "frontend: mark test as a frontend test"
    )
    config.addinivalue_line(
        "markers", "api: mark test as an API test"
    )
    config.addinivalue_line(
        "markers", "database: mark test as a database test"
    )
    config.addinivalue_line(
        "markers", "workflow: mark test as a workflow test"
    )
