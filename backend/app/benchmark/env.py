"""Environment facts and Spark availability checks (never launches Spark by itself)."""
import importlib.metadata as md
import os
import platform
import re
import shutil
import subprocess


def _ver(pkg: str):
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


def java_info() -> dict:
    """Locate Java via JAVA_HOME then PATH and parse `java -version`."""
    home = os.environ.get("JAVA_HOME")
    exe = None
    if home:
        cand = os.path.join(home, "bin", "java.exe" if os.name == "nt" else "java")
        exe = cand if os.path.isfile(cand) else None
    exe = exe or shutil.which("java")
    info = {"found": exe is not None, "java_home_set": bool(home), "major": None, "version": None}
    if not exe:
        return info
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15).stderr
        m = re.search(r'version "([^"]+)"', out)
        if m:
            info["version"] = m.group(1)
            parts = m.group(1).split(".")
            info["major"] = int(parts[1] if parts[0] == "1" else re.sub(r"\D.*", "", parts[0]))
    except (OSError, subprocess.SubprocessError):
        pass
    return info


SUPPORTED_JAVA = (17, 21)  # Spark 4.0 documentation: "Spark runs on Java 17/21"


def spark_status() -> dict:
    """Cheap, honest pre-flight. 'available' means prerequisites look right, not that Spark was started."""
    py = _ver("pyspark")
    j = java_info()
    reasons = []
    if py is None:
        reasons.append("PySpark is not installed.")
    if not j["found"]:
        reasons.append("Java was not found. Install JDK 17 or 21 and set JAVA_HOME (or add java to PATH).")
    elif j["major"] not in SUPPORTED_JAVA:
        reasons.append(f"Java {j['version']} detected; Spark 4 documents Java 17 or 21.")
    return {"available": not reasons, "pyspark": py, "java": j, "reasons": reasons}


def environment() -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
        mem = {"total_mb": round(vm.total / 2**20), "available_mb": round(vm.available / 2**20)}
        physical = psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001
        mem, physical = {}, None
    j = java_info()
    return {"python": platform.python_version(), "pandas": _ver("pandas"), "numpy": _ver("numpy"),
            "pyarrow": _ver("pyarrow"), "pyspark": _ver("pyspark"), "java": j.get("version"),
            "os": platform.platform(), "machine": platform.machine(), "cpu_logical": os.cpu_count(),
            "cpu_physical": physical, **mem}
