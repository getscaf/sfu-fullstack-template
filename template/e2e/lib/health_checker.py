"""
Service health check verification module.
Provides async health checking for HTTP and database services.
"""

import asyncio
import json
from typing import Dict, Optional
import yaml
import httpx
import psycopg2
from psycopg2 import sql


class HealthStatus:
    """Enum-like class for health status."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class HealthChecker:
    """
    Checks the health of multiple services asynchronously.
    Supports HTTP services and database services.
    """
    
    def __init__(self, config_path: str, timeout_seconds: int = 120):
        """
        Initialize health checker with configuration.
        
        Args:
            config_path: Path to health-checks.yaml configuration file
            timeout_seconds: Maximum time to wait for services to become healthy
        """
        self.config_path = config_path
        self.timeout_seconds = timeout_seconds
        self.config = self._load_config()
        self.statuses: Dict[str, str] = {}
        self.errors: Dict[str, str] = {}
    
    def _load_config(self) -> dict:
        """Load and parse YAML configuration file."""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
    async def check_all_services(self) -> Dict[str, str]:
        """
        Check health of all configured services with timeout.
        
        Returns:
            Dictionary mapping service name to health status
            
        Raises:
            asyncio.TimeoutError: If services don't become healthy within timeout
        """
        services = self.config.get('services', {})
        
        # Check all services concurrently until timeout
        start_time = asyncio.get_event_loop().time()
        check_interval = self.config.get('global', {}).get('check_interval_seconds', 2)
        
        while True:
            # Check all services
            tasks = []
            service_names = []
            
            for name, service_config in services.items():
                service_names.append(name)
                if service_config.get('type') == 'database':
                    tasks.append(self._check_database_service(name, service_config))
                else:
                    tasks.append(self._check_http_service(name, service_config))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update statuses
            all_healthy = True
            for name, result in zip(service_names, results):
                if isinstance(result, Exception):
                    self.statuses[name] = HealthStatus.UNHEALTHY
                    self.errors[name] = str(result)
                    all_healthy = False
                else:
                    self.statuses[name] = result
                    if result != HealthStatus.HEALTHY:
                        all_healthy = False
            
            # If all healthy, return success
            if all_healthy:
                return self.statuses
            
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= self.timeout_seconds:
                # Return current statuses with timeout error
                for name in self.statuses:
                    if self.statuses[name] != HealthStatus.HEALTHY:
                        self.statuses[name] = HealthStatus.TIMEOUT
                return self.statuses
            
            # Wait before next check
            await asyncio.sleep(check_interval)
    
    async def check_service(self, service_name: str) -> bool:
        """
        Check health of a single service.
        
        Args:
            service_name: Name of service to check
            
        Returns:
            True if healthy, False otherwise
        """
        services = self.config.get('services', {})
        if service_name not in services:
            return False
        
        service_config = services[service_name]
        
        try:
            if service_config.get('type') == 'database':
                result = await self._check_database_service(service_name, service_config)
            else:
                result = await self._check_http_service(service_name, service_config)
            
            return result == HealthStatus.HEALTHY
        except Exception:
            return False
    
    async def _check_http_service(self, name: str, config: dict) -> str:
        """
        Check HTTP service health.
        
        Args:
            name: Service name
            config: Service configuration
            
        Returns:
            Health status string
        """
        url = config.get('url', '')
        endpoint = config.get('health_endpoint', '/')
        expected_status = config.get('expected_status', 200)
        timeout = config.get('timeout_seconds', 30)
        
        full_url = f"{url}{endpoint}".rstrip('/')
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(full_url, follow_redirects=True)
                
                if response.status_code == expected_status:
                    return HealthStatus.HEALTHY
                else:
                    self.errors[name] = f"Expected {expected_status}, got {response.status_code}"
                    return HealthStatus.UNHEALTHY
        
        except asyncio.TimeoutError:
            self.errors[name] = "Request timeout"
            return HealthStatus.UNHEALTHY
        except Exception as e:
            self.errors[name] = str(e)
            return HealthStatus.UNHEALTHY
    
    async def _check_database_service(self, name: str, config: dict) -> str:
        """
        Check database service health.
        
        Args:
            name: Service name
            config: Service configuration
            
        Returns:
            Health status string
        """
        host = config.get('host', 'localhost')
        port = config.get('port', 5432)
        database = config.get('database', 'postgres')
        user = config.get('user', 'postgres')
        password = config.get('password', '')
        health_check = config.get('health_check', 'SELECT 1')
        
        try:
            # Try to connect and execute query
            conn = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                connect_timeout=config.get('timeout_seconds', 30)
            )
            
            cursor = conn.cursor()
            cursor.execute(health_check)
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result is not None:
                return HealthStatus.HEALTHY
            else:
                self.errors[name] = "Health check query returned no result"
                return HealthStatus.UNHEALTHY
        
        except psycopg2.OperationalError as e:
            self.errors[name] = f"Connection failed: {str(e)}"
            return HealthStatus.UNHEALTHY
        except psycopg2.ProgrammingError as e:
            self.errors[name] = f"Query error: {str(e)}"
            return HealthStatus.UNHEALTHY
        except Exception as e:
            self.errors[name] = str(e)
            return HealthStatus.UNHEALTHY
    
    @property
    def service_statuses(self) -> Dict[str, str]:
        """Get current service statuses."""
        return self.statuses.copy()
    
    def get_error(self, service_name: str) -> Optional[str]:
        """Get error message for a service."""
        return self.errors.get(service_name)
