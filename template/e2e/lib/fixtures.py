"""
Test data and fixture utilities.
Provides test data loading and cleanup functions.
"""

import yaml
from typing import Dict, Any, Optional


def load_test_data(config_path: str) -> Dict[str, Any]:
    """
    Load test data from YAML configuration file.
    
    Args:
        config_path: Path to test-data.yaml
        
    Returns:
        Dictionary containing test data
    """
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse test data configuration: {e}")


def get_test_user(test_data: Dict[str, Any], index: int = 0) -> Optional[Dict[str, str]]:
    """
    Get a test user from test data.
    
    Args:
        test_data: Test data dictionary
        index: Index of user to retrieve
        
    Returns:
        Test user dictionary or None
    """
    users = test_data.get('test_users', [])
    if index < len(users):
        return users[index]
    return None


def get_test_items(test_data: Dict[str, Any]) -> list:
    """
    Get test items from test data.
    
    Args:
        test_data: Test data dictionary
        
    Returns:
        List of test items
    """
    return test_data.get('test_items', [])


def get_database_config(test_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Get database configuration from test data.
    
    Args:
        test_data: Test data dictionary
        
    Returns:
        Database configuration dictionary
    """
    return test_data.get('database', {})


class TestDataFixture:
    """Context manager for test data lifecycle."""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.data = None
    
    def __enter__(self):
        """Load test data."""
        self.data = load_test_data(self.config_path)
        return self.data
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cleanup test data."""
        self.data = None
