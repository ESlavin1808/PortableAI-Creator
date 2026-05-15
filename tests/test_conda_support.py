"""Тесты для conda_support.py"""
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from conda_support import CondaConverter, CONDA_TO_PIP


class TestCondaConverter:
    def test_conda_to_pip_table(self):
        """Таблица конвертации должна содержать ключевые пакеты."""
        assert CONDA_TO_PIP["pytorch"] == "torch"
        assert CONDA_TO_PIP["faiss"] == "faiss-cpu"
        assert CONDA_TO_PIP["ninja"] == "ninja"
        # Пакеты без pip-аналога
        assert CONDA_TO_PIP["cudatoolkit"] == ""
        assert CONDA_TO_PIP["ffmpeg"] == ""

    def test_parse_simple_yml(self):
        """Парсинг простого environment.yml."""
        yml_content = """
name: test-env
dependencies:
  - python=3.11
  - torch>=2.0
  - numpy
  - pip
  - pip:
    - requests
    - flask>=2.0
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            f.write(yml_content)
            yml_path = Path(f.name)

        try:
            converter = CondaConverter(yml_path)
            pip_deps, skipped = converter.convert()
            assert "torch>=2.0" in pip_deps or "torch>=2.0" in str(pip_deps)
            assert "requests" in pip_deps
            assert "flask>=2.0" in pip_deps
        finally:
            yml_path.unlink(missing_ok=True)

    def test_skip_conda_only(self):
        """Пакеты без pip-аналога должны попадать в skipped."""
        yml_content = """
dependencies:
  - cudatoolkit=11.8
  - pytorch
  - ffmpeg
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            f.write(yml_content)
            yml_path = Path(f.name)

        try:
            converter = CondaConverter(yml_path)
            pip_deps, skipped = converter.convert()
            assert "pytorch" not in pip_deps  # pytorch → torch
            assert "cudatoolkit" in str(skipped) or "cudatoolkit" in str(converter.logs)
        finally:
            yml_path.unlink(missing_ok=True)
