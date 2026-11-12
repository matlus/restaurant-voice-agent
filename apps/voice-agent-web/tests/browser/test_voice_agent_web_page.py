# Browser tests of the call page: real Chromium loads the page from the real host, whose conversation domain talks to a
# scripted Realtime service on this machine. Chromium's fake microphone stands in for the guest. They prove the page
# starts and ends a call, sends the guest's speech, shows the server's reason when a call fails, and recovers from a
# double click. Chromium comes from `playwright install chromium`; VOICE_AGENT_TEST_CHROMIUM_PATH can name another build.

import os
import time
from collections.abc import Callable, Iterator
from http import HTTPStatus
from pathlib import Path
from typing import Final

import pytest
from conversation_acceptance_support.realtime_voice_service_scripted import RealtimeVoiceServiceScripted
from conversation_acceptance_support.service_locator_testing import create_domain_facade
from playwright.sync_api import Browser, Locator, Page, expect, sync_playwright
from web_test_support.page_host import PageHost

from voice_agent_web.main import create_app

CHROMIUM_PATH_VARIABLE_NAME: Final[str] = "VOICE_AGENT_TEST_CHROMIUM_PATH"
# A microphone and its permission without a person to grant it, and audio that may start before a gesture.
CHROMIUM_ARGUMENTS: Final[list[str]] = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]
READY_STATUS: Final[str] = "Press the button to call."
CONNECTED_STATUS: Final[str] = "Connected. Go ahead and talk."
ENDED_STATUS: Final[str] = "Call ended."
PROVIDER_ACCESS_DENIED_REASON: Final[str] = "The voice service refused access"
IDLE_STATE: Final[str] = "idle"
SERVICE_OBSERVATION_TIMEOUT_SECONDS: Final[float] = 5.0
SERVICE_OBSERVATION_POLL_MILLISECONDS: Final[float] = 50.0


@pytest.fixture
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        chromium_browser: Browser = playwright.chromium.launch(
            executable_path=os.environ.get(CHROMIUM_PATH_VARIABLE_NAME) or None, args=CHROMIUM_ARGUMENTS
        )
        yield chromium_browser
        chromium_browser.close()


def create_page_host(realtime_voice_service_scripted: RealtimeVoiceServiceScripted, tmp_path: Path) -> PageHost:
    restaurant_database_path: Path = tmp_path / "restaurant.sqlite3"
    return PageHost(create_app(lambda: create_domain_facade(realtime_voice_service_scripted, restaurant_database_path)))


def open_call_page(browser: Browser, page_host: PageHost) -> Page:
    page: Page = browser.new_page()
    page.goto(page_host.base_url)
    # The button only starts a call once the voices have loaded.
    expect(page.locator("#status")).to_have_text(READY_STATUS)
    return page


def observe_voice_service(page: Page, observation: Callable[[], bool]) -> bool:
    """Whether the voice service shows what observation looks for before the time runs out. The service runs on its own
    thread, so the page is left to run while the test looks."""
    deadline: float = time.monotonic() + SERVICE_OBSERVATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if observation():
            return True
        page.wait_for_timeout(SERVICE_OBSERVATION_POLL_MILLISECONDS)
    return False


class TestVoiceAgentWebPage:
    def test_Page_WhenTheGuestCallsAndHangsUp_ThenTheCallConnectsTheGuestIsHeardAndTheCallEnds(self, browser: Browser, tmp_path: Path) -> None:
        expected_outcome: tuple[bool, bool] = (True, True)

        with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_page_host(realtime_voice_service_scripted, tmp_path) as page_host,
        ):
            page: Page = open_call_page(browser, page_host)
            status_line_locator: Locator = page.locator("#status")
            call_button_locator: Locator = page.locator("#call-button")
            call_button_locator.click()
            expect(status_line_locator).to_have_text(CONNECTED_STATUS)
            actual_guest_was_heard: bool = observe_voice_service(
                page, lambda: bool(realtime_voice_service_scripted.captured_realtime_sessions[0].guest_audio)
            )
            call_button_locator.click()
            expect(status_line_locator).to_have_text(ENDED_STATUS)
            # Looked for while the host still runs: stopping the host would close the session whatever the page did.
            actual_session_was_closed: bool = observe_voice_service(
                page, lambda: realtime_voice_service_scripted.captured_realtime_sessions[0].was_closed_by_client
            )

        actual_outcome: tuple[bool, bool] = (actual_guest_was_heard, actual_session_was_closed)
        assert actual_outcome == expected_outcome

    def test_Page_WhenTheVoiceServiceRefusesAccess_ThenTheStatusLineGivesTheServersReasonAndTheButtonCanCallAgain(
        self, browser: Browser, tmp_path: Path
    ) -> None:
        with (
            RealtimeVoiceServiceScripted(handshake_refusal_status=HTTPStatus.UNAUTHORIZED) as realtime_voice_service_scripted,
            create_page_host(realtime_voice_service_scripted, tmp_path) as page_host,
        ):
            page: Page = open_call_page(browser, page_host)
            call_button_locator: Locator = page.locator("#call-button")
            call_button_locator.click()

            expect(page.locator("#status")).to_have_text(PROVIDER_ACCESS_DENIED_REASON)
            expect(call_button_locator).to_have_attribute("data-state", IDLE_STATE)

    def test_Page_WhenTheGuestDoubleClicksTheButton_ThenTheSecondClickCancelsTheCallAndTheNextCallConnects(
        self, browser: Browser, tmp_path: Path
    ) -> None:
        expected_every_session_was_closed: bool = True

        with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_page_host(realtime_voice_service_scripted, tmp_path) as page_host,
        ):
            page: Page = open_call_page(browser, page_host)
            status_line_locator: Locator = page.locator("#status")
            call_button_locator: Locator = page.locator("#call-button")
            call_button_locator.dblclick()
            expect(status_line_locator).to_have_text(ENDED_STATUS)
            call_button_locator.click()
            expect(status_line_locator).to_have_text(CONNECTED_STATUS)
            call_button_locator.click()
            expect(status_line_locator).to_have_text(ENDED_STATUS)
            # Every session the page opened, the cancelled one included, was closed by the page. Looked for while the
            # host still runs, as stopping it would close them all whatever the page did.
            actual_every_session_was_closed: bool = observe_voice_service(
                page,
                lambda: (
                    bool(realtime_voice_service_scripted.captured_realtime_sessions)
                    and all(
                        captured_realtime_session.was_closed_by_client
                        for captured_realtime_session in realtime_voice_service_scripted.captured_realtime_sessions
                    )
                ),
            )

        assert actual_every_session_was_closed == expected_every_session_was_closed
