import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kg_admin", ROOT / "scripts/release/kg/kg_admin.py")
ADMIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADMIN)


def test_existing_production_container_is_rejected():
    with pytest.raises(ValueError):
        ADMIN.execute("viz_virtuoso_1", "checkpoint;")


def test_sql_error_fails_even_when_isql_exit_code_is_zero():
    with patch.object(ADMIN.subprocess, "run", return_value=SimpleNamespace(
        returncode=0, stdout="*** Error 37000: [Virtuoso Driver]bad SQL\n", stderr=""
    )):
        assert ADMIN.execute("eq_kg_3_0_0", "bad SQL;")[1]


def test_credentials_are_resolved_inside_candidate_container():
    with patch.object(ADMIN.subprocess, "run", return_value=SimpleNamespace(
        returncode=0, stdout="Done.\n", stderr=""
    )) as called:
        assert not ADMIN.execute("eq_kg_3_0_0", "checkpoint;")[1]
        assert '"$DBA_PASSWORD"' in called.call_args.args[0][-1]
        assert called.call_args.kwargs["input"] == "checkpoint;"
