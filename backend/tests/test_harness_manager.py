from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.harness_adapter import HarnessAdapterError, HarnessManager
from app.storage import ConversationStore


class FakeRunner:
    def __init__(self, result: object | None = None) -> None:
        self.closed = False
        self.result = result
        self.session_ids: list[str] = []

    def close(self) -> None:
        self.closed = True

    def run(
        self,
        _prompt: str,
        *,
        session_id: str,
        on_notification: object,
    ) -> object:
        del on_notification
        self.session_ids.append(session_id)
        return self.result


class BlockingRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.stop_requested = threading.Event()
        self.close_calls = 0
        self.concurrent_closes = 0
        self.maximum_concurrent_closes = 0
        self._close_lock = threading.Lock()

    def run(
        self,
        _prompt: str,
        *,
        session_id: str,
        on_notification: object,
    ) -> object:
        del session_id, on_notification
        self.started.set()
        self.stop_requested.wait(timeout=2)
        raise RuntimeError("runtime closed")

    def close(self) -> None:
        with self._close_lock:
            self.close_calls += 1
            self.concurrent_closes += 1
            self.maximum_concurrent_closes = max(
                self.maximum_concurrent_closes,
                self.concurrent_closes,
            )
        self.stop_requested.set()
        # Keep the first close in progress long enough for the runner thread's
        # exception cleanup to exercise the ownership race deterministically.
        time.sleep(0.05)
        with self._close_lock:
            self.concurrent_closes -= 1
            self.closed = True


class HarnessManagerCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.settings = Settings.from_env(
            {"DATA_DIR": str(root / "data")},
            root_dir=root,
        )
        self.store = ConversationStore(self.settings.conversation_root)
        self.conversation_id = "conversation_123456"
        self.store.create_or_reuse(self.conversation_id)
        self.manager = HarnessManager(self.settings, self.store)
        self.manager.sdk_installed = lambda: True  # type: ignore[method-assign]
        self.settings.cordis_path.write_text("# test runtime\n", encoding="utf-8")

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        self.temporary.cleanup()

    async def test_cancel_during_runner_creation_closes_created_runtime(self) -> None:
        started = threading.Event()
        release = threading.Event()
        runner = FakeRunner()

        def create_runner(_conversation_id: str) -> FakeRunner:
            started.set()
            release.wait(timeout=2)
            return runner

        self.manager._create_runner = create_runner  # type: ignore[method-assign]
        creation = asyncio.create_task(
            self.manager._runner_for(self.conversation_id, "run-old")
        )
        self.assertTrue(await asyncio.to_thread(started.wait, 1))
        self.assertTrue(
            await self.manager.cancel(self.conversation_id, run_id="run-old")
        )
        release.set()
        with self.assertRaises(HarnessAdapterError) as caught:
            await creation
        self.assertEqual("AGENT_CANCELLED", caught.exception.code)
        self.assertTrue(runner.closed)
        self.assertNotIn(self.conversation_id, self.manager._busy)

    async def test_old_cleanup_cannot_release_new_generation(self) -> None:
        old_runner = FakeRunner()
        new_runner = FakeRunner()
        self.manager._runners[self.conversation_id] = new_runner
        self.manager._busy[self.conversation_id] = "run-new"

        await self.manager._discard_runner(
            self.conversation_id,
            old_runner,
            "run-old",
        )

        self.assertIs(new_runner, self.manager._runners[self.conversation_id])
        self.assertEqual("run-new", self.manager._busy[self.conversation_id])
        self.assertFalse(old_runner.closed)
        self.assertFalse(new_runner.closed)

    async def test_active_cancel_and_run_cleanup_close_runner_once(self) -> None:
        runner = BlockingRunner()
        self.manager._runners[self.conversation_id] = runner
        running = asyncio.create_task(
            self.manager.run(
                self.conversation_id,
                "取消这轮",
                lambda _notification: None,
                run_id="run-cancel-close-once",
            )
        )
        self.assertTrue(await asyncio.to_thread(runner.started.wait, 1))

        self.assertTrue(
            await self.manager.cancel(
                self.conversation_id,
                run_id="run-cancel-close-once",
            )
        )
        with self.assertRaises(HarnessAdapterError) as caught:
            await running

        self.assertEqual("AGENT_CANCELLED", caught.exception.code)
        self.assertEqual(1, runner.close_calls)
        self.assertEqual(1, runner.maximum_concurrent_closes)

    async def test_each_http_run_uses_a_unique_runtime_session_id(self) -> None:
        first_runner = FakeRunner(
            SimpleNamespace(final_response="续聊成功", finish_reason="stop")
        )
        second_runner = FakeRunner(
            SimpleNamespace(final_response="再次续聊成功", finish_reason="stop")
        )
        self.manager._runners[self.conversation_id] = first_runner
        self.manager._create_runner = lambda _conversation_id: second_runner  # type: ignore[method-assign]

        first_result = await self.manager.run(
            self.conversation_id,
            "继续",
            lambda _notification: None,
            run_id="run-generation-one",
            session_generation=1,
        )

        self.assertEqual(
            f"web-{self.conversation_id}-g1-rrun-generation-one",
            first_result.session_id,
        )
        second_result = await self.manager.run(
            self.conversation_id,
            "再次继续",
            lambda _notification: None,
            run_id="run-generation-one-again",
            session_generation=1,
        )
        self.assertNotEqual(first_result.session_id, second_result.session_id)
        self.assertEqual([first_result.session_id], first_runner.session_ids)
        self.assertEqual([second_result.session_id], second_runner.session_ids)
        self.assertTrue(first_runner.closed)
        self.assertTrue(second_runner.closed)
        self.assertNotIn(self.conversation_id, self.manager._runners)

    async def test_busy_is_held_until_response_validation_finishes(self) -> None:
        runner = FakeRunner(
            SimpleNamespace(final_response="有效回复", finish_reason="stop")
        )
        self.manager._runners[self.conversation_id] = runner
        validation_started = asyncio.Event()
        release_validation = asyncio.Event()
        take_cancelled = self.manager._take_cancelled

        async def slow_cancel_check(run_id: str) -> bool:
            validation_started.set()
            await release_validation.wait()
            return await take_cancelled(run_id)

        self.manager._take_cancelled = slow_cancel_check  # type: ignore[method-assign]
        running = asyncio.create_task(
            self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: None,
                run_id="run-validating",
            )
        )
        await asyncio.wait_for(validation_started.wait(), timeout=1)

        with self.assertRaises(HarnessAdapterError) as caught:
            await self.manager._runner_for(self.conversation_id, "run-too-early")
        self.assertEqual("AGENT_BUSY", caught.exception.code)

        release_validation.set()
        result = await running
        self.assertEqual("有效回复", result.final_response)
        self.assertTrue(runner.closed)

    async def test_empty_final_response_is_a_failed_run(self) -> None:
        runner = FakeRunner(
            SimpleNamespace(final_response="  ", finish_reason="stop")
        )
        self.manager._runners[self.conversation_id] = runner

        with self.assertRaises(HarnessAdapterError) as caught:
            await self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: None,
                run_id="run-empty",
            )

        self.assertEqual("AGENT_EMPTY_RESPONSE", caught.exception.code)
        self.assertTrue(runner.closed)
        self.assertNotIn(self.conversation_id, self.manager._runners)

    async def test_error_finish_reason_is_a_failed_run(self) -> None:
        runner = FakeRunner(
            SimpleNamespace(final_response="partial", finish_reason="error")
        )
        self.manager._runners[self.conversation_id] = runner

        with self.assertRaises(HarnessAdapterError) as caught:
            await self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: None,
                run_id="run-error",
            )

        self.assertEqual("AGENT_RESPONSE_ERROR", caught.exception.code)
        self.assertTrue(runner.closed)
        self.assertNotIn(self.conversation_id, self.manager._runners)


if __name__ == "__main__":
    unittest.main()
