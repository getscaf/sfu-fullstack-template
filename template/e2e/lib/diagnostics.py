"""
Diagnostic collection module.
Gathers logs, pod status, and other debugging information.
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List


class DiagnosticsCollector:
    """Collects diagnostic information when tests fail."""
    
    def __init__(self, output_path: Optional[str] = None):
        """
        Initialize diagnostics collector.
        
        Args:
            output_path: Path to save diagnostics report
        """
        self.output_path = output_path or "diagnostics.log"
        self.sections: List[str] = []
    
    def collect_all(self) -> str:
        """
        Collect all available diagnostics.
        
        Returns:
            Complete diagnostics report as string
        """
        report = []
        report.append("=" * 60)
        report.append("DIAGNOSTIC REPORT")
        report.append("=" * 60)
        report.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
        report.append("")
        
        report.append(self.collect_pod_status())
        report.append("")
        
        report.append(self.collect_pod_logs())
        report.append("")
        
        report.append(self.collect_service_status())
        report.append("")
        
        report.append(self.collect_tilt_status())
        report.append("")
        
        report.append(self.collect_kubernetes_events())
        
        full_report = "\n".join(report)
        
        if self.output_path:
            self._save_report(full_report)
        
        return full_report
    
    def collect_pod_status(self) -> str:
        """Collect Kubernetes pod status."""
        section = []
        section.append("=" * 60)
        section.append("POD STATUS")
        section.append("=" * 60)
        
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'pods', '-A'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                section.append(result.stdout)
            else:
                section.append(f"Error: {result.stderr}")
        except Exception as e:
            section.append(f"Failed to get pod status: {e}")
        
        return "\n".join(section)
    
    def collect_pod_logs(self) -> str:
        """Collect logs from all pods."""
        section = []
        section.append("=" * 60)
        section.append("POD LOGS")
        section.append("=" * 60)
        
        try:
            # Get pod names with namespaces
            result = subprocess.run(
                ['kubectl', 'get', 'pods', '-A', '-o', 
                 'jsonpath={range .items[*]}{.metadata.namespace}{" "}{.metadata.name}{"\n"}{end}'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                section.append(f"Error getting pods: {result.stderr}")
                return "\n".join(section)
            
            # Parse pod list and collect logs
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    namespace, pod_name = parts[0], parts[1]
                    section.append(f"--- Logs for {namespace}/{pod_name} ---")
                    try:
                        log_result = subprocess.run(
                            ['kubectl', 'logs', '-n', namespace, pod_name, 
                             '--timestamps=true', '--tail=50'],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if log_result.returncode == 0:
                            section.append(log_result.stdout or "[No logs]")
                        else:
                            section.append(f"[Could not retrieve logs: {log_result.stderr}]")
                    except Exception as e:
                        section.append(f"[Error: {e}]")
                    
                    section.append("")
        
        except Exception as e:
            section.append(f"Failed to collect pod logs: {e}")
        
        return "\n".join(section)
    
    def collect_service_status(self) -> str:
        """Collect Kubernetes service status."""
        section = []
        section.append("=" * 60)
        section.append("SERVICE STATUS")
        section.append("=" * 60)
        
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'svc', '-A'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                section.append(result.stdout)
            else:
                section.append(f"Error: {result.stderr}")
        except Exception as e:
            section.append(f"Failed to get service status: {e}")
        
        return "\n".join(section)
    
    def collect_tilt_status(self) -> str:
        """Collect Tilt status."""
        section = []
        section.append("=" * 60)
        section.append("TILT STATUS")
        section.append("=" * 60)
        
        try:
            result = subprocess.run(
                ['tilt', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                section.append(result.stdout or "Tilt not running")
            else:
                section.append(f"Error: {result.stderr}")
        except Exception as e:
            section.append(f"Failed to get Tilt status: {e}")
        
        return "\n".join(section)
    
    def collect_kubernetes_events(self) -> str:
        """Collect Kubernetes events."""
        section = []
        section.append("=" * 60)
        section.append("KUBERNETES EVENTS")
        section.append("=" * 60)
        
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'events', '-A'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                section.append(result.stdout)
            else:
                section.append(f"Error: {result.stderr}")
        except Exception as e:
            section.append(f"Failed to get events: {e}")
        
        return "\n".join(section)
    
    def _save_report(self, report: str):
        """Save diagnostics report to file."""
        try:
            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, 'w') as f:
                f.write(report)
        except Exception as e:
            print(f"Failed to save diagnostics: {e}")
