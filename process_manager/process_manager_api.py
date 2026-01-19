"""
Service Supervisor - Robust Process Management API for Windows Production Environment
Manages Backend (FastAPI) and Frontend (React/Node) services with auto-restart and logging.
"""
import asyncio
import logging
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from collections import deque

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configure logging with UTF-8 encoding
# Ensure stdout/stderr use UTF-8 encoding on Windows
if sys.platform == "win32":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Get the process_manager directory
PROCESS_MANAGER_DIR = Path(__file__).parent.resolve()
LOGS_DIR = PROCESS_MANAGER_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Get workspace root (parent of process_manager)
WORKSPACE_ROOT = PROCESS_MANAGER_DIR.parent.resolve()
BACKEND_DIR = WORKSPACE_ROOT / "backend"
FRONTEND_DIR = WORKSPACE_ROOT / "frontend"


class ServiceConfig(BaseModel):
    """Configuration for a service"""
    name: str
    command: List[str] = Field(..., description="Command and arguments as list")
    working_dir: Path = Field(..., description="Working directory for the service")
    env: Optional[Dict[str, str]] = None
    enabled: bool = True


class ServiceStatus(BaseModel):
    """Status of a service"""
    name: str
    status: str = Field(..., description="Running, Stopped, or Crashed")
    pid: Optional[int] = None
    uptime_seconds: Optional[float] = None
    restart_count: int = 0
    last_restart: Optional[str] = None


class ProcessInfo:
    """Internal process information"""
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.start_time: Optional[datetime] = None
        self.restart_count = 0
        self.last_restart: Optional[datetime] = None
        self.restart_times: deque = deque(maxlen=5)  # Track last 5 restarts
        self.stdout_file: Optional[Path] = None
        self.stderr_file: Optional[Path] = None
        self.stdout_handle = None
        self.stderr_handle = None


class ServiceManager:
    """Manages service processes with auto-restart and logging"""
    
    def __init__(self):
        self.services: Dict[str, ServiceConfig] = {}
        self.processes: Dict[str, ProcessInfo] = {}
        self.monitor_task: Optional[asyncio.Task] = None
        self.shutdown_event = asyncio.Event()
        
        # Initialize service configurations
        self._init_services()
    
    def _test_python_executable(self, python_exe: Path) -> bool:
        """Test if Python executable actually works"""
        try:
            result = subprocess.run(
                [str(python_exe), "--version"],
                capture_output=True,
                timeout=5,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Python test failed for {python_exe}: {e}")
            return False
    
    def _init_services(self):
        """Initialize service configurations"""
        # Backend service - use Python from backend's venv to run run.py
        backend_python = BACKEND_DIR / "venv" / "Scripts" / "python.exe"
        backend_venv_path = BACKEND_DIR / "venv"
        use_system_python = False
        venv_env = {}
        
        if not backend_python.exists():
            # Fallback to system Python if venv not found
            logger.warning(f"Backend venv not found at {backend_python}, using system Python")
            use_system_python = True
        else:
            # Test if venv Python actually works (it might have broken paths)
            if not self._test_python_executable(backend_python):
                logger.warning(
                    f"Backend venv Python at {backend_python} is broken (likely created on different machine). "
                    f"Using system Python with venv activation. To fix, recreate venv: "
                    f"cd backend && rmdir /s /q venv && python -m venv venv && venv\\Scripts\\activate.bat && pip install -r requirements.txt"
                )
                use_system_python = True
            else:
                logger.info(f"Using backend Python: {backend_python}")
        
        # If using system Python but venv exists, activate venv via environment variables
        if use_system_python and backend_venv_path.exists():
            venv_scripts = backend_venv_path / "Scripts"
            venv_lib = backend_venv_path / "Lib" / "site-packages"
            
            # Add venv Scripts to PATH and site-packages to PYTHONPATH
            current_path = os.environ.get("PATH", "")
            venv_env["PATH"] = f"{venv_scripts};{current_path}"
            
            # Set VIRTUAL_ENV variable (used by some packages)
            venv_env["VIRTUAL_ENV"] = str(backend_venv_path)
            
            # Add site-packages to PYTHONPATH
            current_pythonpath = os.environ.get("PYTHONPATH", "")
            if current_pythonpath:
                venv_env["PYTHONPATH"] = f"{venv_lib};{current_pythonpath}"
            else:
                venv_env["PYTHONPATH"] = str(venv_lib)
            
            logger.info(f"Activating venv via environment variables: {venv_scripts}")
        
        # Use run.py instead of -m app.main (app.main is not executable as module)
        python_to_use = sys.executable if use_system_python else str(backend_python)
        self.services["backend"] = ServiceConfig(
            name="backend",
            command=[python_to_use, "run.py"],
            working_dir=BACKEND_DIR,
            env=venv_env if venv_env else None,
            enabled=True
        )
        
        # Frontend service
        # Check if npm is available
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        self.services["frontend"] = ServiceConfig(
            name="frontend",
            command=[npm_cmd, "start"],
            working_dir=FRONTEND_DIR,
            enabled=True
        )
        
        # Ollama service
        # Try to find ollama.exe in PATH or common locations
        ollama_exe = None
        ollama_working_dir = None
        
        # Check if ollama.exe is in PATH
        try:
            result = subprocess.run(
                ["where", "ollama.exe"] if sys.platform == "win32" else ["which", "ollama"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                ollama_exe = result.stdout.strip().split('\n')[0]
                ollama_working_dir = Path(ollama_exe).parent
                logger.info(f"Found Ollama at: {ollama_exe}")
        except Exception as e:
            logger.debug(f"Could not find ollama.exe in PATH: {e}")
        
        # If not found, try common locations
        if not ollama_exe or not Path(ollama_exe).exists():
            common_paths = [
                Path(os.path.expanduser("~")) / "Desktop" / "ollama.exe",
                Path("C:/Program Files/Ollama/ollama.exe"),
                Path("C:/Program Files (x86)/Ollama/ollama.exe"),
            ]
            for path in common_paths:
                if path.exists():
                    ollama_exe = str(path)
                    ollama_working_dir = path.parent
                    logger.info(f"Found Ollama at: {ollama_exe}")
                    break
        
        if ollama_exe and Path(ollama_exe).exists():
            # Set environment variables for CORS support
            ollama_env = {
                "OLLAMA_ORIGINS": "*",
                "OLLAMA_HOST": "0.0.0.0:11434"
            }
            
            self.services["ollama"] = ServiceConfig(
                name="ollama",
                command=[ollama_exe, "serve"],
                working_dir=ollama_working_dir if ollama_working_dir else Path(ollama_exe).parent,
                env=ollama_env,
                enabled=True
            )
            logger.info(f"Ollama service configured: {ollama_exe}")
        else:
            logger.warning("⚠️ Ollama executable not found. Ollama service will not be available.")
            logger.warning("   Please ensure ollama.exe is in PATH or specify its location.")
        
        # ComfyUI service
        # Try to find ComfyUI installation
        comfyui_path = None
        comfyui_main_py = None
        
        # Check environment variable first
        comfyui_env_path = os.environ.get("COMFYUI_PATH")
        if comfyui_env_path:
            comfyui_path = Path(comfyui_env_path)
            comfyui_main_py = comfyui_path / "main.py"
            if comfyui_main_py.exists():
                logger.info(f"✅ Found ComfyUI via COMFYUI_PATH: {comfyui_path}")
        
        # If not found, try common locations (prioritize the user's location)
        if not comfyui_main_py or not comfyui_main_py.exists():
            common_paths = [
                Path("C:/ComfyUI_windows_portable/ComfyUI"),  # User's location - highest priority
                Path("C:/ComfyUI"),
                Path(os.path.expanduser("~/ComfyUI")),
                Path(os.path.expanduser("~/Desktop/ComfyUI")),
            ]
            
            for path in common_paths:
                main_py = path / "main.py"
                if main_py.exists():
                    comfyui_path = path
                    comfyui_main_py = main_py
                    logger.info(f"✅ Found ComfyUI at common location: {comfyui_path}")
                    break
        
        # If still not found, try to infer from workflow path in backend config
        if not comfyui_main_py or not comfyui_main_py.exists():
            try:
                # Try to read backend config to get workflow path
                backend_config_path = BACKEND_DIR / "app" / "config.py"
                if backend_config_path.exists():
                    with open(backend_config_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        # Look for COMFYUI_WORKFLOW_PATH
                        import re
                        match = re.search(r'COMFYUI_WORKFLOW_PATH.*?=.*?r?"([^"]+)"', content)
                        if match:
                            workflow_path = Path(match.group(1))
                            # Try parent directories
                            for parent in [workflow_path.parent, workflow_path.parent.parent]:
                                main_py = parent / "main.py"
                                if main_py.exists():
                                    comfyui_path = parent
                                    comfyui_main_py = main_py
                                    logger.info(f"Found ComfyUI from workflow path: {comfyui_path}")
                                    break
            except Exception as e:
                logger.debug(f"Could not infer ComfyUI path from config: {e}")
        
        if comfyui_main_py and comfyui_main_py.exists():
            # Try to find embedded Python first (for portable ComfyUI)
            # Check if python_embeded exists in parent directory (C:/ComfyUI_windows_portable/python_embeded)
            python_exe = None
            comfyui_base = comfyui_path.parent if comfyui_path.name == "ComfyUI" else comfyui_path
            embedded_python = comfyui_base / "python_embeded" / "python.exe"
            
            if embedded_python.exists():
                python_exe = str(embedded_python)
                logger.info(f"✅ Found ComfyUI embedded Python: {python_exe}")
            else:
                # Embedded Python not found - disable service to prevent dependency errors
                logger.warning(f"⚠️ ComfyUI embedded Python not found at {embedded_python}")
                logger.warning(f"   ComfyUI service will be DISABLED to prevent dependency errors.")
                logger.warning(f"   Please ensure ComfyUI is installed with embedded Python or install dependencies manually.")
                # Create disabled service entry for API compatibility
                self.services["comfyui"] = ServiceConfig(
                    name="comfyui",
                    command=[],
                    working_dir=comfyui_path,
                    enabled=False
                )
                return  # Exit, do not configure service further
            
            # Set environment variables for ComfyUI
            comfyui_env = {
                "PYTHONIOENCODING": "utf-8"
            }
            
            # Use the same command as in run_nvidia_gpu.bat
            self.services["comfyui"] = ServiceConfig(
                name="comfyui",
                command=[python_exe, "main.py", "--listen", "0.0.0.0", "--port", "8188"],
                working_dir=comfyui_path,
                env=comfyui_env,
                enabled=True
            )
            logger.info(f"✅ ComfyUI service configured: {comfyui_path}")
            logger.info(f"   Python: {python_exe}")
            logger.info(f"   Command: {' '.join(self.services['comfyui'].command)}")
        else:
            logger.warning("⚠️ ComfyUI not found. ComfyUI service will not be available.")
            logger.warning("   Please set COMFYUI_PATH environment variable or install ComfyUI in a common location.")
            logger.warning("   Common locations: C:/ComfyUI_windows_portable/ComfyUI, C:/ComfyUI")
            # Create disabled service entry for API compatibility
            self.services["comfyui"] = ServiceConfig(
                name="comfyui",
                command=[],
                working_dir=WORKSPACE_ROOT,
                enabled=False
            )
        
        logger.info(f"Initialized {len(self.services)} services: {list(self.services.keys())}")
    
    def _get_log_files(self, service_name: str) -> Tuple[Path, Path]:
        """Get log file paths for a service"""
        stdout_log = LOGS_DIR / f"{service_name}.out.log"
        stderr_log = LOGS_DIR / f"{service_name}.err.log"
        return stdout_log, stderr_log
    
    def start_service(self, service_name: str) -> bool:
        """Start a service"""
        if service_name not in self.services:
            logger.error(f"Unknown service: {service_name}")
            return False
        
        config = self.services[service_name]
        if not config.enabled:
            logger.warning(f"Service {service_name} is disabled")
            return False
        
        # Stop existing process if running
        if service_name in self.processes:
            self.stop_service(service_name)
            time.sleep(1)  # Give it time to stop
        
        try:
            # Validate command and working directory
            if not config.working_dir.exists():
                logger.error(f"Working directory does not exist: {config.working_dir}")
                return False
            
            # For backend, check if run.py exists
            if service_name == "backend":
                run_py = config.working_dir / "run.py"
                if not run_py.exists():
                    logger.error(f"run.py not found in {config.working_dir}")
                    return False
                # Verify Python executable exists
                python_exe = Path(config.command[0])
                if not python_exe.exists():
                    logger.error(f"Python executable not found: {python_exe}")
                    logger.error(f"This usually means the venv was created on a different machine.")
                    logger.error(f"Please recreate the venv: cd backend && rmdir /s /q venv && python -m venv venv")
                    return False
            
            # For ComfyUI, check if main.py exists
            if service_name == "comfyui":
                main_py = config.working_dir / "main.py"
                if not main_py.exists():
                    logger.error(f"main.py not found in {config.working_dir}")
                    logger.error(f"Please ensure ComfyUI is installed at: {config.working_dir}")
                    logger.error(f"Or set COMFYUI_PATH environment variable to the correct path")
                    return False
                # Verify Python executable exists
                python_exe = Path(config.command[0])
                if not python_exe.exists():
                    logger.error(f"Python executable not found: {python_exe}")
                    return False
            
            # Get log files
            stdout_log, stderr_log = self._get_log_files(service_name)
            
            # Open log files in append mode
            stdout_handle = open(stdout_log, "a", encoding="utf-8", buffering=1)
            stderr_handle = open(stderr_log, "a", encoding="utf-8", buffering=1)
            
            # Prepare environment
            env = os.environ.copy()
            # Set UTF-8 encoding for Python processes to avoid encoding errors
            env["PYTHONIOENCODING"] = "utf-8"
            if config.env:
                env.update(config.env)
            
            # Windows-specific flags
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            logger.info(f"Starting service '{service_name}': {' '.join(config.command)}")
            logger.info(f"Working directory: {config.working_dir}")
            
            # Start process
            process = subprocess.Popen(
                config.command,
                cwd=str(config.working_dir),
                stdout=stdout_handle,
                stderr=stderr_handle,
                env=env,
                creationflags=creation_flags,
                text=True
            )
            
            # Store process info
            proc_info = ProcessInfo(service_name)
            proc_info.process = process
            proc_info.pid = process.pid
            proc_info.start_time = datetime.now()
            proc_info.stdout_file = stdout_log
            proc_info.stderr_file = stderr_log
            proc_info.stdout_handle = stdout_handle
            proc_info.stderr_handle = stderr_handle
            
            self.processes[service_name] = proc_info
            
            # Log startup
            logger.info(f"✅ Service '{service_name}' started with PID {process.pid}")
            stdout_handle.write(f"\n{'='*80}\n")
            stdout_handle.write(f"Service '{service_name}' started at {datetime.now().isoformat()}\n")
            stdout_handle.write(f"PID: {process.pid}\n")
            stdout_handle.write(f"Command: {' '.join(config.command)}\n")
            stdout_handle.write(f"{'='*80}\n\n")
            stdout_handle.flush()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start service '{service_name}': {e}", exc_info=True)
            return False
    
    def stop_service(self, service_name: str) -> bool:
        """Stop a service"""
        if service_name not in self.processes:
            logger.warning(f"Service '{service_name}' is not running")
            return True
        
        proc_info = self.processes[service_name]
        
        try:
            if proc_info.process:
                logger.info(f"Stopping service '{service_name}' (PID: {proc_info.pid})")
                
                # On Windows, use taskkill for more reliable termination
                if sys.platform == "win32":
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc_info.pid)],
                            capture_output=True,
                            timeout=10
                        )
                    except Exception as e:
                        logger.warning(f"taskkill failed for PID {proc_info.pid}: {e}")
                        # Fallback to terminate
                        try:
                            proc_info.process.terminate()
                            proc_info.process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc_info.process.kill()
                else:
                    # Non-Windows shutdown
                    proc_info.process.terminate()
                    try:
                        proc_info.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc_info.process.kill()
                
                # Close log file handles
                if proc_info.stdout_handle:
                    try:
                        proc_info.stdout_handle.write(f"\n{'='*80}\n")
                        proc_info.stdout_handle.write(f"Service '{service_name}' stopped at {datetime.now().isoformat()}\n")
                        proc_info.stdout_handle.write(f"{'='*80}\n\n")
                        proc_info.stdout_handle.flush()
                        proc_info.stdout_handle.close()
                    except:
                        pass
                
                if proc_info.stderr_handle:
                    try:
                        proc_info.stderr_handle.close()
                    except:
                        pass
                
                logger.info(f"✅ Service '{service_name}' stopped")
            
            # Remove from processes dict
            del self.processes[service_name]
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to stop service '{service_name}': {e}", exc_info=True)
            # Still remove from dict even if stop failed
            if service_name in self.processes:
                del self.processes[service_name]
            return False

    def restart_service(self, service_name: str) -> bool:
        """Restart a service"""
        logger.info(f"Restarting service '{service_name}'")
        self.stop_service(service_name)
        time.sleep(1)
        return self.start_service(service_name)
    
    def get_service_status(self, service_name: str) -> ServiceStatus:
        """Get status of a service"""
        if service_name not in self.services:
            raise ValueError(f"Unknown service: {service_name}")
        
        if service_name not in self.processes:
            return ServiceStatus(
                name=service_name,
                status="Stopped",
                pid=None,
                uptime_seconds=None,
                restart_count=0,
                last_restart=None
            )
        
        proc_info = self.processes[service_name]
        
        # Check if process is still alive
        if proc_info.process:
            return_code = proc_info.process.poll()
            if return_code is not None:
                # Process has terminated
                status = "Crashed"
            else:
                status = "Running"
        else:
            status = "Stopped"
        
        # Calculate uptime
        uptime = None
        if proc_info.start_time:
            uptime = (datetime.now() - proc_info.start_time).total_seconds()
        
        # Format last restart
        last_restart_str = None
        if proc_info.last_restart:
            last_restart_str = proc_info.last_restart.isoformat()
        
        return ServiceStatus(
            name=service_name,
            status=status,
            pid=proc_info.pid,
            uptime_seconds=uptime,
            restart_count=proc_info.restart_count,
            last_restart=last_restart_str
        )
    
    def _can_restart(self, proc_info: ProcessInfo) -> bool:
        """Check if service can be restarted (rate limiting)"""
        now = datetime.now()
        # Remove restart times older than 1 minute
        while proc_info.restart_times and (now - proc_info.restart_times[0]).total_seconds() > 60:
            proc_info.restart_times.popleft()
        
        # Check if we've restarted more than 5 times in the last minute
        if len(proc_info.restart_times) >= 5:
            logger.warning(
                f"Service '{proc_info.service_name}' has restarted {len(proc_info.restart_times)} "
                f"times in the last minute. Rate limiting restarts."
            )
            return False
        
        return True
    
    async def monitor_services(self):
        """Monitor services and auto-restart if they crash"""
        logger.info("Starting service monitor...")
        
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                
                for service_name in list(self.processes.keys()):
                    proc_info = self.processes[service_name]
                    
                    if proc_info.process:
                        return_code = proc_info.process.poll()
                        
                        if return_code is not None:
                            # Process has crashed
                            logger.error(
                                f"❌ Service '{service_name}' crashed with return code {return_code}"
                            )
                            
                            # Try to read last few lines from stderr log for diagnostics
                            try:
                                if proc_info.stderr_file and proc_info.stderr_file.exists():
                                    with open(proc_info.stderr_file, "r", encoding="utf-8", errors="ignore") as f:
                                        stderr_lines = f.readlines()
                                        if stderr_lines:
                                            last_lines = stderr_lines[-10:]  # Last 10 lines
                                            logger.error(f"Last stderr output from '{service_name}':")
                                            for line in last_lines:
                                                logger.error(f"  {line.rstrip()}")
                            except Exception as e:
                                logger.debug(f"Could not read stderr log: {e}")
                            
                            # Log to stderr file
                            if proc_info.stderr_handle:
                                try:
                                    proc_info.stderr_handle.write(
                                        f"\n{'='*80}\n"
                                        f"Service '{service_name}' crashed at {datetime.now().isoformat()}\n"
                                        f"Return code: {return_code}\n"
                                        f"{'='*80}\n\n"
                                    )
                                    proc_info.stderr_handle.flush()
                                except:
                                    pass
                            
                            # Close file handles
                            if proc_info.stdout_handle:
                                try:
                                    proc_info.stdout_handle.close()
                                except:
                                    pass
                            if proc_info.stderr_handle:
                                try:
                                    proc_info.stderr_handle.close()
                                except:
                                    pass
                            
                            # Check for dependency errors (ModuleNotFoundError) - don't auto-restart
                            is_dependency_error = False
                            try:
                                if proc_info.stderr_file and proc_info.stderr_file.exists():
                                    with open(proc_info.stderr_file, "r", encoding="utf-8", errors="ignore") as f:
                                        stderr_content = f.read()
                                        if "ModuleNotFoundError" in stderr_content or "No module named" in stderr_content:
                                            is_dependency_error = True
                            except Exception:
                                pass
                            
                            if is_dependency_error:
                                logger.error(
                                    f"❌ Service '{service_name}' crashed due to missing dependencies. "
                                    f"Auto-restart disabled. Please install dependencies manually."
                                )
                                logger.error(
                                    f"   For ComfyUI, ensure dependencies are installed in the embedded Python environment."
                                )
                                # Remove from processes dict
                                del self.processes[service_name]
                            elif self._can_restart(proc_info):
                                logger.info(f"🔄 Auto-restarting service '{service_name}'...")
                                proc_info.restart_count += 1
                                proc_info.last_restart = datetime.now()
                                proc_info.restart_times.append(datetime.now())
                                
                                # Remove from processes dict temporarily
                                del self.processes[service_name]
                                
                                # Restart
                                if self.start_service(service_name):
                                    logger.info(f"✅ Service '{service_name}' auto-restarted successfully")
                                else:
                                    logger.error(f"❌ Failed to auto-restart service '{service_name}'")
                            else:
                                logger.error(
                                    f"❌ Service '{service_name}' exceeded restart limit. "
                                    f"Manual intervention required."
                                )
                                # Remove from processes dict
                                del self.processes[service_name]
                                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
        
        logger.info("Service monitor stopped")
    
    def start_all_services(self):
        """Start all enabled services"""
        logger.info("Starting all enabled services...")
        
        # Define startup order: Ollama first (if available), then Backend, then Frontend
        startup_order = ["ollama", "backend", "frontend"]
        
        # Start services in order
        for service_name in startup_order:
            if service_name in self.services and self.services[service_name].enabled:
                self.start_service(service_name)
                time.sleep(2)  # Stagger startup
        
        # Start any other services that weren't in the ordered list
        for service_name, config in self.services.items():
            if config.enabled and service_name not in startup_order:
                self.start_service(service_name)
                time.sleep(2)  # Stagger startup
    
    def stop_all_services(self):
        """Stop all services"""
        logger.info("Stopping all services...")
        for service_name in list(self.processes.keys()):
            self.stop_service(service_name)


# Global service manager instance
service_manager = ServiceManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI app"""
    # Startup
    logger.info("🚀 Service Supervisor starting up...")
    service_manager.start_all_services()
    
    # Start monitor task
    service_manager.monitor_task = asyncio.create_task(service_manager.monitor_services())
    
    yield
    
    # Shutdown
    logger.info("🛑 Service Supervisor shutting down...")
    service_manager.shutdown_event.set()
    
    # Wait for monitor to stop
    if service_manager.monitor_task:
        service_manager.monitor_task.cancel()
        try:
            await service_manager.monitor_task
        except asyncio.CancelledError:
            pass
    
    # Stop all services
    service_manager.stop_all_services()
    logger.info("✅ Service Supervisor shutdown complete")


# Create FastAPI app with lifespan
app = FastAPI(
    title="Service Supervisor",
    description="Robust Service Supervisor for managing Backend and Frontend services",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Service Supervisor",
        "version": "2.0.0",
        "endpoints": {
            "health": "GET /health",
            "restart": "POST /restart/{service_name}",
            "stop": "POST /stop/{service_name}",
            "logs": "GET /logs/{service_name}"
        }
    }


@app.get("/health")
async def get_health():
    """Get health status of all services"""
    services_status = {}
    
    for service_name in service_manager.services.keys():
        services_status[service_name] = service_manager.get_service_status(service_name).dict()
    
    return {
        "status": "ok",
        "services": services_status,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/restart/{service_name}")
async def restart_service(service_name: str):
    """Manually restart a service"""
    if service_name not in service_manager.services:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    success = service_manager.restart_service(service_name)
    
    if success:
        return {
            "success": True,
            "message": f"Service '{service_name}' restarted successfully",
            "status": service_manager.get_service_status(service_name).dict()
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restart service '{service_name}'"
        )


@app.post("/stop/{service_name}")
async def stop_service(service_name: str):
    """Stop a service"""
    if service_name not in service_manager.services:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    success = service_manager.stop_service(service_name)
    
    if success:
        return {
            "success": True,
            "message": f"Service '{service_name}' stopped successfully"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop service '{service_name}'"
        )


@app.post("/process/start")
async def start_process(service: str):
    """Start a process (for compatibility with old API)"""
    if service not in service_manager.services:
        raise HTTPException(status_code=404, detail=f"Service '{service}' not found")
    
    success = service_manager.start_service(service)
    
    if success:
        return {
            "success": True,
            "message": f"Service '{service}' started successfully",
            "status": service_manager.get_service_status(service).dict()
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start service '{service}'"
        )


@app.get("/logs/{service_name}")
async def get_logs(service_name: str, lines: int = 50):
    """Get the last N lines of a service's error log"""
    if service_name not in service_manager.services:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    _, stderr_log = service_manager._get_log_files(service_name)
    
    if not stderr_log.exists():
        return {
            "service": service_name,
            "log_file": str(stderr_log),
            "lines": [],
            "message": "Log file does not exist yet"
        }
    
    try:
        with open(stderr_log, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        return {
            "service": service_name,
            "log_file": str(stderr_log),
            "lines": [line.rstrip() for line in last_lines],
            "total_lines": len(all_lines),
            "returned_lines": len(last_lines)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {str(e)}")


def is_port_in_use(port: int) -> bool:
    """Проверяет, занят ли порт"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return False
        except OSError:
            return True


def find_process_using_port(port: int) -> Optional[int]:
    """Находит PID процесса, который использует порт (Windows)"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                pid = int(parts[-1])
                                # Не возвращаем PID текущего процесса
                                if pid != os.getpid():
                                    return pid
                            except ValueError:
                                pass
    except Exception:
        pass
    return None


def find_free_port(start_port: int, max_attempts: int = 10) -> int:
    """Находит свободный порт, начиная с start_port"""
    import socket
    for i in range(max_attempts):
        port = start_port + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Не удалось найти свободный порт в диапазоне {start_port}-{start_port + max_attempts - 1}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PROCESS_API_PORT", "8888"))
    
    # Проверяем, занят ли порт
    if is_port_in_use(port):
        logger.warning(f"⚠️ Порт {port} уже занят.")
        
        # Пытаемся найти процесс, который занимает порт
        pid = find_process_using_port(port)
        if pid:
            logger.warning(f"Порт {port} используется процессом с PID {pid}")
            logger.warning(f"Чтобы освободить порт, выполните: taskkill /F /PID {pid}")
        
        logger.info(f"Пытаюсь найти свободный порт, начиная с {port}...")
        try:
            original_port = port
            port = find_free_port(port)
            logger.warning(f"⚠️ ВНИМАНИЕ: Использую порт {port} вместо {original_port}")
            logger.warning(f"⚠️ Service Supervisor API будет доступен на http://localhost:{port}")
            logger.warning(f"⚠️ Если вы используете другой порт, обновите настройки или завершите процесс на порту {original_port}")
        except RuntimeError as e:
            logger.error(f"❌ {e}")
            logger.error(f"Пожалуйста, освободите порт {port} или укажите другой порт через переменную окружения PROCESS_API_PORT")
            if pid:
                logger.error(f"Или завершите процесс: taskkill /F /PID {pid}")
            sys.exit(1)
    
    logger.info(f"Запуск Service Supervisor на http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)