# Ponto de entrada para Streamlit Cloud
# Redireciona para app/ui/dashboard.py
import runpy, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
runpy.run_path(str(Path(__file__).parent / "app" / "ui" / "dashboard.py"), run_name="__main__")
