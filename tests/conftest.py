"""Point the ops DB and runtime exports at a temp folder so tests never touch data/ops.db."""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="dw_ops_test_")
os.environ.setdefault("OPS_DB", os.path.join(_TMP, "ops_test.db"))
os.environ.setdefault("OPS_EXPORT_DIR", os.path.join(_TMP, "exports"))
os.environ.setdefault("OPS_SECRET", "test-secret-not-for-production")
