from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.harness_adapter import HarnessAdapterError, HarnessFollowup, HarnessManager
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


class RestartSignalRunner(FakeRunner):
    """Compatibility-path runner that asks the manager to rotate its session."""

    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        super().close()

    def run(
        self,
        _prompt: str,
        *,
        session_id: str,
        on_notification: object,
    ) -> object:
        self.session_ids.append(session_id)
        assert callable(on_notification)
        # ``observe`` raises the manager's private restart signal when the
        # callback returns a restart follow-up.  Returning is therefore not
        # expected for this first-generation runner.
        on_notification({"method": "session.event", "payload": {"event": {"type": "todo/write"}}})
        raise AssertionError("restart callback did not interrupt the old runner")


class BlockingRestartSignalRunner(RestartSignalRunner):
    """Restart runner whose close can be paused to exercise cancellation races."""

    def __init__(self) -> None:
        super().__init__()
        self.close_started = threading.Event()
        self.release_close = threading.Event()

    def close(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        self.release_close.wait(timeout=2)
        self.closed = True


class FakeClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.prompts: list[tuple[str, list[dict[str, str]]]] = []

    def session_prompt(
        self,
        session_id: str,
        content: list[dict[str, str]],
    ) -> None:
        if self.failure is not None:
            raise self.failure
        self.prompts.append((session_id, content))


class PromptingRunner(FakeRunner):
    def __init__(self, *, client: FakeClient | None = None) -> None:
        super().__init__(
            SimpleNamespace(final_response="恢复成功", finish_reason="stop")
        )
        self.client = client or FakeClient()

    def run(
        self,
        _prompt: str,
        *,
        session_id: str,
        on_notification: object,
    ) -> object:
        self.session_ids.append(session_id)
        assert callable(on_notification)
        on_notification({"type": "todo/write"})
        return self.result


class FakeSubscription:
    def __init__(self) -> None:
        self.notifications: list[object] = []
        self.next_calls = 0

    def __enter__(self) -> FakeSubscription:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        return None

    def next(self) -> object:
        self.next_calls += 1
        if not self.notifications:
            raise AssertionError("owned session waited beyond the final idle")
        return self.notifications.pop(0)


class OwnedClient:
    def __init__(self, *, buffered_tail: bool = False) -> None:
        self.subscription = FakeSubscription()
        self.prompt_calls: list[tuple[str, list[dict[str, str]], object]] = []
        self.buffered_tail = buffered_tail

    @staticmethod
    def _event(session_id: str, event: dict[str, object]) -> object:
        return SimpleNamespace(
            method="session.event",
            payload={"sessionId": session_id, "event": event},
        )

    @staticmethod
    def _idle(session_id: str) -> object:
        return SimpleNamespace(
            method="session.status",
            payload={"sessionId": session_id, "status": "idle"},
        )

    def subscribe_session_notifications(self, _session_id: str) -> FakeSubscription:
        return self.subscription

    def session_prompt(
        self,
        session_id: str,
        content: list[dict[str, str]],
        *,
        notification_subscription: object,
    ) -> str:
        self.prompt_calls.append((session_id, content, notification_subscription))
        message_id = f"message-{len(self.prompt_calls)}"
        if len(self.prompt_calls) == 1:
            notifications: list[object] = [
                self._event(
                    session_id,
                    {
                        "type": "agent/inbox/spliced",
                        "data": {"inserted": [{"id": message_id}]},
                    },
                ),
                self._event(session_id, {"type": "todo/write", "data": {}}),
            ]
            if self.buffered_tail:
                # These are the notifications observed in production after a
                # rejected todo_write and before the server correction splice:
                # a result envelope without a tool name, followed by a queued
                # shell call that the splice cancels.
                notifications.extend(
                    [
                        self._event(
                            session_id,
                            {
                                "type": "tool/result",
                                "data": {
                                    "turn": 1,
                                    "step": 59,
                                    "message": {
                                        "source": {
                                            "kind": "tool",
                                            "callId": "todo-call-1",
                                        },
                                        "content": [
                                            {
                                                "type": "tool-result",
                                                "toolCallId": "todo-call-1",
                                            }
                                        ],
                                    },
                                },
                            },
                        ),
                        self._event(
                            session_id,
                            {
                                "type": "tool/call",
                                "data": {
                                    "callId": "queued-shell-1",
                                    "name": "bash",
                                    "arguments": '{"command":"echo queued"}',
                                },
                            },
                        ),
                    ]
                )
            # This idle belongs to the original prompt and must not end the
            # owned interval once a correction has been queued.
            notifications.append(self._idle(session_id))
            self.subscription.notifications.extend(notifications)
        elif len(self.prompt_calls) == 2:
            self.subscription.notifications.extend(
                [
                    self._event(
                        session_id,
                        {
                            "type": "agent/inbox/spliced",
                            "data": {"inserted": [{"id": message_id}]},
                        },
                    ),
                    self._event(
                        session_id,
                        {
                            "type": "assistant/message",
                            "data": {
                                "message": {
                                    "content": [
                                        {"type": "text", "text": "纠正处理完成"}
                                    ]
                                }
                            },
                        },
                    ),
                    self._event(
                        session_id,
                        {"type": "turn/end", "data": {"reason": {"kind": "stop"}}},
                    ),
                    self._idle(session_id),
                ]
            )
        else:
            raise AssertionError("only one correction may be queued")
        return message_id


class NormalOwnedClient(OwnedClient):
    def session_prompt(
        self,
        session_id: str,
        content: list[dict[str, str]],
        *,
        notification_subscription: object,
    ) -> str:
        self.prompt_calls.append((session_id, content, notification_subscription))
        if len(self.prompt_calls) != 1:
            raise AssertionError("normal run must submit exactly one prompt")
        message_id = "message-normal"
        self.subscription.notifications.extend(
            [
                self._event(
                    session_id,
                    {
                        "type": "agent/inbox/spliced",
                        "data": {"inserted": [{"id": message_id}]},
                    },
                ),
                self._event(
                    session_id,
                    {
                        "type": "assistant/message",
                        "data": {
                            "message": {
                                "content": [{"type": "text", "text": "正常完成"}]
                            }
                        },
                    },
                ),
                self._event(
                    session_id,
                    {"type": "turn/end", "data": {"reason": {"kind": "stop"}}},
                ),
                self._idle(session_id),
            ]
        )
        return message_id


class OwnedRunner(FakeRunner):
    def __init__(self, *, client: OwnedClient | None = None) -> None:
        super().__init__()
        self.client = client or OwnedClient()
        self.started_sessions: list[str] = []
        self.run_called = False

    def start_session(self, session_id: str) -> object:
        self.started_sessions.append(session_id)
        return object()

    def run(
        self,
        _prompt: str,
        *,
        session_id: str,
        on_notification: object,
    ) -> object:
        del session_id, on_notification
        self.run_called = True
        raise AssertionError("the production-owned path must not call runner.run")


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
        skill_root = root / "skills"
        controller = skill_root / "comprehensive-real-estate-expert" / "SKILL.md"
        controller.parent.mkdir(parents=True)
        controller.write_text("---\nname: comprehensive-real-estate-expert\n---\n")
        self.settings = Settings.from_env(
            {
                "DATA_DIR": str(root / "data"),
                "HARNESS_SKILL_DIRS": str(skill_root),
            },
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

    async def test_missing_controller_skill_fails_before_runtime_start(self) -> None:
        controller = (
            self.settings.harness_skill_dirs[0]
            / "comprehensive-real-estate-expert"
            / "SKILL.md"
        )
        controller.unlink()

        self.assertFalse(self.manager.status()["controller_skill_configured"])
        with self.assertRaises(HarnessAdapterError) as caught:
            await self.manager.run(
                self.conversation_id,
                "研究项目",
                lambda _notification: None,
                run_id="run-missing-controller",
            )

        self.assertEqual("AGENT_CONTROLLER_SKILL_MISSING", caught.exception.code)
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

    async def test_restart_keeps_busy_lease_until_replacement_is_installed(self) -> None:
        old_runner = RestartSignalRunner()
        new_runner = FakeRunner(
            SimpleNamespace(final_response="恢复后完成", finish_reason="stop")
        )
        self.manager._runners[self.conversation_id] = old_runner
        create_started = threading.Event()
        release_create = threading.Event()

        def create_runner(_conversation_id: str) -> FakeRunner:
            # The old process must be closed before construction starts.  The
            # busy lease, however, must remain owned by the original run.
            self.assertTrue(old_runner.closed)
            create_started.set()
            release_create.wait(timeout=2)
            return new_runner

        self.manager._create_runner = create_runner  # type: ignore[method-assign]
        running = asyncio.create_task(
            self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: HarnessFollowup(
                    "权威清单重置",
                    restart_session=True,
                ),
                run_id="run-restart-lease",
            )
        )
        self.assertTrue(await asyncio.to_thread(create_started.wait, 1))

        with self.assertRaises(HarnessAdapterError) as caught:
            await self.manager._runner_for(self.conversation_id, "run-stealer")
        self.assertEqual("AGENT_BUSY", caught.exception.code)

        release_create.set()
        result = await running
        self.assertEqual("恢复后完成", result.final_response)
        self.assertEqual(
            "web-"
            + self.conversation_id
            + "-g1-rrun-restart-lease",
            result.session_id,
        )
        self.assertEqual(1, old_runner.close_calls)
        self.assertTrue(new_runner.closed)
        self.assertNotIn(self.conversation_id, self.manager._busy)
        self.assertNotIn(self.conversation_id, self.manager._runners)

    async def test_cancel_during_old_restart_close_does_not_double_close(self) -> None:
        old_runner = BlockingRestartSignalRunner()
        self.manager._runners[self.conversation_id] = old_runner
        create_called = threading.Event()

        def create_runner(_conversation_id: str) -> FakeRunner:
            create_called.set()
            raise AssertionError("cancellation must prevent replacement creation")

        self.manager._create_runner = create_runner  # type: ignore[method-assign]
        running = asyncio.create_task(
            self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: HarnessFollowup(
                    "权威清单重置",
                    restart_session=True,
                ),
                run_id="run-restart-cancel-close",
            )
        )
        self.assertTrue(await asyncio.to_thread(old_runner.close_started.wait, 1))

        # During the old close the runner has been detached, but the busy lease
        # is intentionally still held.  cancel() records the marker and must
        # not invoke close() a second time.
        self.assertTrue(
            await self.manager.cancel(
                self.conversation_id,
                run_id="run-restart-cancel-close",
            )
        )
        old_runner.release_close.set()

        with self.assertRaises(HarnessAdapterError) as caught:
            await running
        self.assertEqual("AGENT_CANCELLED", caught.exception.code)
        self.assertEqual(1, old_runner.close_calls)
        self.assertFalse(create_called.is_set())
        self.assertNotIn(self.conversation_id, self.manager._busy)
        self.assertNotIn(self.conversation_id, self.manager._runners)

    async def test_restart_creation_failure_releases_busy_and_keeps_old_closed(self) -> None:
        old_runner = RestartSignalRunner()
        self.manager._runners[self.conversation_id] = old_runner

        def create_runner(_conversation_id: str) -> FakeRunner:
            self.assertTrue(old_runner.closed)
            raise RuntimeError("replacement unavailable")

        self.manager._create_runner = create_runner  # type: ignore[method-assign]
        with self.assertRaises(HarnessAdapterError) as caught:
            await self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: HarnessFollowup(
                    "权威清单重置",
                    restart_session=True,
                ),
                run_id="run-restart-create-failure",
            )

        self.assertEqual("AGENT_RUN_FAILED", caught.exception.code)
        self.assertEqual(1, old_runner.close_calls)
        self.assertNotIn(self.conversation_id, self.manager._busy)
        self.assertNotIn(self.conversation_id, self.manager._runners)

    async def test_cancel_after_replacement_creation_closes_uninstalled_candidate(self) -> None:
        old_runner = RestartSignalRunner()
        new_runner = FakeRunner(
            SimpleNamespace(final_response="不应返回", finish_reason="stop")
        )
        self.manager._runners[self.conversation_id] = old_runner
        candidate_created = threading.Event()
        release_create = threading.Event()

        def create_runner(_conversation_id: str) -> FakeRunner:
            candidate_created.set()
            release_create.wait(timeout=2)
            return new_runner

        self.manager._create_runner = create_runner  # type: ignore[method-assign]
        running = asyncio.create_task(
            self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: HarnessFollowup(
                    "权威清单重置",
                    restart_session=True,
                ),
                run_id="run-restart-cancel-create",
            )
        )
        self.assertTrue(await asyncio.to_thread(candidate_created.wait, 1))
        self.assertTrue(
            await self.manager.cancel(
                self.conversation_id,
                run_id="run-restart-cancel-create",
            )
        )
        release_create.set()

        with self.assertRaises(HarnessAdapterError) as caught:
            await running
        self.assertEqual("AGENT_CANCELLED", caught.exception.code)
        self.assertTrue(old_runner.closed)
        self.assertTrue(new_runner.closed)
        self.assertNotIn(self.conversation_id, self.manager._busy)
        self.assertNotIn(self.conversation_id, self.manager._runners)

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

    async def test_notification_followup_is_injected_into_active_session(self) -> None:
        runner = PromptingRunner()
        self.manager._runners[self.conversation_id] = runner

        result = await self.manager.run(
            self.conversation_id,
            "继续",
            lambda _notification: HarnessFollowup("权威清单重置"),
            run_id="run-checklist-repair",
            session_generation=2,
        )

        self.assertEqual("恢复成功", result.final_response)
        self.assertEqual(
            [
                (
                    result.session_id,
                    [{"type": "text", "text": "权威清单重置"}],
                )
            ],
            runner.client.prompts,
        )
        self.assertTrue(runner.closed)

    async def test_notification_followup_failure_aborts_and_discards_runner(self) -> None:
        runner = PromptingRunner(client=FakeClient(failure=RuntimeError("closed")))
        self.manager._runners[self.conversation_id] = runner

        with self.assertRaises(HarnessAdapterError) as caught:
            await self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: HarnessFollowup("权威清单重置"),
                run_id="run-checklist-repair-failure",
            )

        self.assertEqual("AGENT_CHECKLIST_RECOVERY_FAILED", caught.exception.code)
        self.assertTrue(runner.closed)
        self.assertNotIn(self.conversation_id, self.manager._runners)

    async def test_owned_followup_waits_past_old_idle_until_correction_idle(self) -> None:
        runner = OwnedRunner()
        self.manager._runners[self.conversation_id] = runner

        def repair_todo(notification: object) -> HarnessFollowup | None:
            payload = getattr(notification, "payload", None)
            event = payload.get("event") if isinstance(payload, dict) else None
            if isinstance(event, dict) and event.get("type") == "todo/write":
                return HarnessFollowup("权威清单重置")
            return None

        result = await self.manager.run(
            self.conversation_id,
            "继续",
            repair_todo,
            run_id="run-owned-checklist-repair",
        )

        self.assertEqual("纠正处理完成", result.final_response)
        self.assertEqual("stop", result.finish_reason)
        self.assertFalse(runner.run_called)
        self.assertEqual([result.session_id], runner.started_sessions)
        self.assertEqual(2, len(runner.client.prompt_calls))
        self.assertTrue(
            all(
                call[2] is runner.client.subscription
                for call in runner.client.prompt_calls
            )
        )
        self.assertGreaterEqual(runner.client.subscription.next_calls, 7)
        self.assertTrue(runner.closed)

    async def test_owned_recovery_restarts_before_buffered_tail(self) -> None:
        runner = OwnedRunner(client=OwnedClient(buffered_tail=True))
        replacement = OwnedRunner(client=NormalOwnedClient())
        self.manager._runners[self.conversation_id] = runner
        created = threading.Event()

        def create_runner(_conversation_id: str) -> OwnedRunner:
            created.set()
            return replacement

        self.manager._create_runner = create_runner  # type: ignore[method-assign]
        observed: list[str] = []

        def repair_todo(notification: object) -> HarnessFollowup | None:
            payload = getattr(notification, "payload", None)
            event = payload.get("event") if isinstance(payload, dict) else None
            if not isinstance(event, dict):
                return None
            event_type = event.get("type")
            if isinstance(event_type, str):
                observed.append(event_type)
            if event_type == "todo/write":
                return HarnessFollowup("权威清单重置", restart_session=True)
            return None

        result = await self.manager.run(
            self.conversation_id,
            "继续",
            repair_todo,
            run_id="run-owned-buffered-tail",
        )

        self.assertEqual("正常完成", result.final_response)
        self.assertEqual("stop", result.finish_reason)
        self.assertEqual(
            [
                "agent/inbox/spliced",
                "todo/write",
                "agent/inbox/spliced",
                "assistant/message",
                "turn/end",
            ],
            observed,
        )
        self.assertTrue(created.is_set())
        self.assertTrue(runner.closed)
        self.assertTrue(replacement.closed)

    async def test_cancel_after_restart_precheck_blocks_replacement_start(self) -> None:
        """Cancellation wins the hand-off even in the async-to-thread gap."""

        old_runner = RestartSignalRunner()
        replacement = FakeRunner(
            SimpleNamespace(final_response="不应启动", finish_reason="stop")
        )
        self.manager._runners[self.conversation_id] = old_runner
        self.manager._create_runner = lambda _conversation_id: replacement  # type: ignore[method-assign]

        original_take_cancelled = self.manager._take_cancelled
        precheck_reached = asyncio.Event()
        release_precheck = asyncio.Event()
        check_count = 0

        async def gated_take_cancelled(run_id: str) -> bool:
            nonlocal check_count
            check_count += 1
            result = await original_take_cancelled(run_id)
            # Initial check=1, restart hand-off check=2, and the next-attempt
            # check=3.  Pause exactly after that check returns False, before
            # the replacement's compatibility ``run`` can claim its gate.
            if check_count == 3 and not result:
                precheck_reached.set()
                await release_precheck.wait()
            return result

        self.manager._take_cancelled = gated_take_cancelled  # type: ignore[method-assign]
        running = asyncio.create_task(
            self.manager.run(
                self.conversation_id,
                "继续",
                lambda _notification: HarnessFollowup(
                    "权威清单重置",
                    restart_session=True,
                ),
                run_id="run-restart-start-race",
            )
        )
        await asyncio.wait_for(precheck_reached.wait(), timeout=1)
        self.assertTrue(
            await self.manager.cancel(
                self.conversation_id,
                run_id="run-restart-start-race",
            )
        )
        release_precheck.set()

        with self.assertRaises(HarnessAdapterError) as caught:
            await running
        self.assertEqual("AGENT_CANCELLED", caught.exception.code)
        self.assertEqual([], replacement.session_ids)
        self.assertTrue(replacement.closed)
        self.assertNotIn(self.conversation_id, self.manager._busy)
        self.assertNotIn(self.conversation_id, self.manager._runners)

    async def test_owned_normal_run_matches_sdk_turn_boundary(self) -> None:
        runner = OwnedRunner(client=NormalOwnedClient())
        self.manager._runners[self.conversation_id] = runner

        result = await self.manager.run(
            self.conversation_id,
            "继续",
            lambda _notification: None,
            run_id="run-owned-normal",
        )

        self.assertEqual("正常完成", result.final_response)
        self.assertEqual("stop", result.finish_reason)
        self.assertEqual(1, len(runner.client.prompt_calls))
        self.assertFalse(runner.run_called)
        self.assertTrue(runner.closed)

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
