"""
Test execution and reporting module.
Provides test runner and report generation utilities.
"""

import subprocess
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional


class TestReport:
    """Represents a test execution report."""
    
    def __init__(self):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.tests: List[Dict[str, Any]] = []
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.duration = 0.0
    
    def add_test(self, name: str, status: str, duration: float, error: Optional[str] = None):
        """Add test result to report."""
        self.tests.append({
            'name': name,
            'status': status,
            'duration': duration,
            'error': error
        })
        
        if status == 'passed':
            self.passed += 1
        elif status == 'failed':
            self.failed += 1
        elif status == 'skipped':
            self.skipped += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            'timestamp': self.timestamp,
            'total': len(self.tests),
            'passed': self.passed,
            'failed': self.failed,
            'skipped': self.skipped,
            'duration': self.duration,
            'tests': self.tests
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert report to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def format_summary(self) -> str:
        """Format report as human-readable summary."""
        total = len(self.tests)
        
        summary = f"""
Test Run Summary
================
Timestamp: {self.timestamp}
Total tests: {total}
  Passed: {self.passed}
  Failed: {self.failed}
  Skipped: {self.skipped}
Duration: {self.duration:.2f}s

Result: {'✓ PASS' if self.failed == 0 else '✗ FAIL'}
"""
        return summary.strip()


class TestRunner:
    """Execute tests and generate reports."""
    
    def __init__(self, test_dir: str, report_path: str):
        """
        Initialize test runner.
        
        Args:
            test_dir: Directory containing tests
            report_path: Path to save test report
        """
        self.test_dir = test_dir
        self.report_path = report_path
        self.report = TestReport()
    
    def run_tests(self) -> TestReport:
        """
        Execute pytest tests.
        
        Returns:
            TestReport object with results
        """
        try:
            # Run pytest with JSON output
            result = subprocess.run(
                ['pytest', self.test_dir, '-v', '--tb=short', '--json-report', 
                 f'--json-report-file={self.report_path}.json'],
                capture_output=True,
                text=True,
                timeout=600
            )
            
            # Parse output and create report
            self._parse_pytest_output(result.stdout, result.returncode)
            
            # Save report
            self.save_report()
            
            return self.report
        
        except subprocess.TimeoutExpired:
            self.report.failed += 1
            self.report.add_test('pytest', 'failed', 0, 'Test execution timeout')
            return self.report
        except Exception as e:
            self.report.failed += 1
            self.report.add_test('pytest', 'failed', 0, str(e))
            return self.report
    
    def _parse_pytest_output(self, output: str, returncode: int):
        """
        Parse pytest output to extract test results.
        
        Args:
            output: pytest stdout output
            returncode: pytest return code
        """
        lines = output.split('\n')
        
        for line in lines:
            # Parse test result lines (e.g., "test_name PASSED 0.123s")
            if 'PASSED' in line or 'FAILED' in line or 'SKIPPED' in line:
                parts = line.split()
                if len(parts) >= 2:
                    test_name = parts[0]
                    if 'PASSED' in line:
                        status = 'passed'
                    elif 'FAILED' in line:
                        status = 'failed'
                    elif 'SKIPPED' in line:
                        status = 'skipped'
                    else:
                        continue
                    
                    # Extract duration if available
                    duration = 0.0
                    for part in parts:
                        if part.endswith('s'):
                            try:
                                duration = float(part[:-1])
                            except ValueError:
                                pass
                    
                    self.report.add_test(test_name, status, duration)
        
        # Set overall duration if available
        for line in lines:
            if 'passed' in line and 'in' in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'in' and i + 1 < len(parts):
                        try:
                            self.report.duration = float(parts[i + 1][:-1])
                        except (ValueError, IndexError):
                            pass
    
    def save_report(self):
        """Save report to file."""
        try:
            Path(self.report_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.report_path, 'w') as f:
                f.write(self.report.to_json())
        except Exception as e:
            print(f"Failed to save report: {e}")
    
    def format_summary(self) -> str:
        """Format and return test summary."""
        return self.report.format_summary()
