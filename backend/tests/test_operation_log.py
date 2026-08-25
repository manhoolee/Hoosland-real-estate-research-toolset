from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from app.operation_log import OperationLog


class OperationLogTests(unittest.TestCase):
    def test_jsonl_redacts_content_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "logs" / "operations.jsonl"
            log = OperationLog(path, retention_days=7)
            log.start()
            log.record(
                "test.operation",
                request_id="request-1",
                content="private-message-sentinel",
                content_characters=24,
                nested={
                    "api_key": "private-key-sentinel",
                    "authorization": "private-token-sentinel",
                    "status": "ok",
                },
            )
            log.close()

            raw = path.read_text(encoding="utf-8")
            record = json.loads(raw)
            self.assertNotIn("private-message-sentinel", raw)
            self.assertNotIn("private-key-sentinel", raw)
            self.assertNotIn("private-token-sentinel", raw)
            self.assertEqual("<redacted>", record["content"])
            self.assertEqual(24, record["content_characters"])
            self.assertEqual("<redacted>", record["nested"]["api_key"])
            self.assertEqual("ok", record["nested"]["status"])
            self.assertEqual(1, record["schema_version"])

    def test_concurrent_records_remain_one_valid_json_object_per_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "logs" / "operations.jsonl"
            log = OperationLog(path)
            log.start()

            def write(worker: int) -> None:
                for sequence in range(30):
                    log.record("test.concurrent", worker=worker, sequence=sequence)

            threads = [threading.Thread(target=write, args=(worker,)) for worker in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            log.close()

            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertEqual(180, len(records))
            self.assertTrue(all(item["event"] == "test.concurrent" for item in records))

    def test_disabled_log_creates_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "logs" / "operations.jsonl"
            log = OperationLog(path, enabled=False)
            log.start()
            log.record("test.disabled")
            log.close()
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
