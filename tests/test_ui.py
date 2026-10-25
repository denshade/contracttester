"""Browser tests for the pages a user actually clicks through."""

import re
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.sync_api import Browser, Page, expect, sync_playwright

from app.factory import create_app
from app.formatting import format_timestamp
from app.seed import (
    ACTIVE_CONTRACT,
    ACTIVE_VERIFIED_AT,
    ACTIVE_VERIFIER,
    BILL_POST,
    BILL_PUBLISHER,
    BILL_POST_PAYLOAD,
    BILL_POST_STATE,
    DOCK_PUBLISHER,
    DOCK_VERIFIER,
    INACTIVE_CONTRACT,
    SCHEMA_TRIGGER,
    LEGACY_VERIFIED_AT,
    LEGACY_VERIFIER,
)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        launched = _launch_browser(playwright)
        yield launched
        launched.close()


@pytest.fixture
def base_url(tmp_path):
    database = tmp_path / "ui.db"
    app = create_app(f"sqlite:///{database.resolve().as_posix()}")
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    _wait_until_ready(server, url)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def page(browser: Browser, base_url: str):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    screen = context.new_page()
    screen.set_default_timeout(8000)
    yield screen
    context.close()


def test_opening_the_app_asks_for_sign_in(page: Page, base_url: str):
    page.goto(base_url + "/")
    expect(page).to_have_url(re.compile(r"/login"))
    expect(page.get_by_role("heading", name="Log in")).to_be_visible()
    expect(page.get_by_text("Temporary sign-in is admin / admin.")).to_be_visible()


def test_wrong_password_stays_on_the_login_page(page: Page, base_url: str):
    _sign_in(page, base_url, password="wrong")
    expect(page.locator(".error")).to_have_text("Incorrect username or password.")
    expect(page).to_have_url(re.compile(r"/login"))
    page.goto(base_url + "/contracts")
    expect(page.locator("#login-submit")).to_be_visible()


def test_sign_in_shows_which_contracts_have_active_verifiers(page: Page, base_url: str):
    _sign_in(page, base_url)
    expect(page.get_by_role("heading", name="Contracts")).to_be_visible()
    expect(page.locator(".org")).to_have_text("Harbor & Co.")
    expect(page.locator(f"tr[data-contract-name='{ACTIVE_CONTRACT}']")).to_have_attribute("data-active", "yes")
    expect(page.locator(f"tr[data-contract-name='{INACTIVE_CONTRACT}']")).to_have_attribute("data-active", "no")
    expect(page.get_by_text("Active verifiers and the publisher reflect the latest version of each contract.")).to_be_visible()
    expect(page.locator(f"tr[data-contract-name='{ACTIVE_CONTRACT}']")).to_have_attribute("data-publisher", BILL_PUBLISHER)
    expect(page.locator(f"tr[data-contract-name='{INACTIVE_CONTRACT}']")).to_have_attribute("data-publisher", DOCK_PUBLISHER)


def test_contract_page_saves_the_publisher_name(page: Page, base_url: str):
    _sign_in(page, base_url)
    page.get_by_role("link", name=ACTIVE_CONTRACT).click()
    expect(page.locator("#publisher-name")).to_have_value(BILL_PUBLISHER)

    page.locator("#publisher-name").fill("   ")
    page.locator("#save-publisher").click()
    expect(page.locator(".error")).to_have_text("Publisher name is required")

    page.locator("#publisher-name").fill("Pier Office")
    page.locator("#save-publisher").click()
    expect(page.locator(".flash")).to_have_text("Publisher saved.")
    expect(page.locator("#publisher-name")).to_have_value("Pier Office")

    page.locator("tr[data-version='1'] a").click()
    expect(page.locator("#publisher-name")).to_have_value(BILL_PUBLISHER)

    page.locator("nav").get_by_role("link", name="Contracts").click()
    expect(page.locator(f"tr[data-contract-name='{ACTIVE_CONTRACT}']")).to_have_attribute("data-publisher", "Pier Office")


def test_contract_page_shows_versions_verifiers_and_statements(page: Page, base_url: str):
    _sign_in(page, base_url)
    page.get_by_role("link", name=ACTIVE_CONTRACT).click()

    expect(page.get_by_role("heading", name=ACTIVE_CONTRACT)).to_be_visible()
    expect(page.locator("tr[data-version='1']")).to_have_attribute("data-active", "no")
    expect(page.locator("tr[data-version='2']")).to_have_attribute("data-active", "yes")
    expect(page.locator("tr[data-version='2']")).to_have_attribute("data-current", "true")

    active = page.locator("#active-verifiers")
    expect(active).to_contain_text(ACTIVE_VERIFIER)
    expect(active).to_contain_text(format_timestamp(ACTIVE_VERIFIED_AT))
    expect(active).to_contain_text("GET /bills/{id}")

    statements = page.locator("#statements")
    expect(statements).to_contain_text(BILL_POST)
    expect(statements).to_contain_text(BILL_POST_STATE)
    expect(statements).to_contain_text(BILL_POST_PAYLOAD)
    expect(statements).to_contain_text(f"{ACTIVE_VERIFIER} v1 · {format_timestamp(ACTIVE_VERIFIED_AT)}")


def test_older_version_shows_its_own_verifier(page: Page, base_url: str):
    _sign_in(page, base_url)
    page.get_by_role("link", name=ACTIVE_CONTRACT).click()
    page.locator("tr[data-version='1'] a").click()

    expect(page.locator(".lede")).to_have_text("Version 1")
    expect(page.locator("tr[data-version='1']")).to_have_attribute("data-current", "true")
    expect(page.locator("#active-verifiers-empty")).to_have_text("This version has no active verifiers.")
    expect(page.locator("#statements")).to_contain_text(
        f"{LEGACY_VERIFIER} v1 · {format_timestamp(LEGACY_VERIFIED_AT)}"
    )
    expect(page.locator("#statements")).not_to_contain_text(ACTIVE_VERIFIER)


def test_removing_a_contract_asks_for_confirmation(page: Page, base_url: str):
    _sign_in(page, base_url)
    page.get_by_role("link", name=ACTIVE_CONTRACT).click()
    page.locator("#remove-contract").click()

    expect(page.get_by_role("heading", name=f"Remove {ACTIVE_CONTRACT}?")).to_be_visible()
    expect(page.get_by_text(f"Are you sure you want to remove {ACTIVE_CONTRACT}?")).to_be_visible()

    page.get_by_role("link", name="Cancel").click()
    expect(page.get_by_role("heading", name=ACTIVE_CONTRACT)).to_be_visible()
    expect(page.locator("#statements")).to_be_visible()

    page.locator("#remove-contract").click()
    page.locator("#confirm-remove").click()
    expect(page.locator(".flash")).to_have_text("Contract removed.")
    expect(page.locator(f"tr[data-contract-name='{ACTIVE_CONTRACT}']")).to_have_count(0)
    expect(page.locator(f"tr[data-contract-name='{INACTIVE_CONTRACT}']")).to_have_count(1)


def test_organization_page_saves_the_name_and_issues_a_token(page: Page, base_url: str):
    _sign_in(page, base_url)
    page.get_by_role("link", name="Organization").click()
    expect(page.locator("#token-empty")).to_have_text("No access token yet.")

    page.fill("#org-name", "   ")
    page.locator("#save-organization").click()
    expect(page.locator(".error")).to_have_text("Organization name is required")

    page.fill("#org-name", "South Pier")
    page.locator("#save-organization").click()
    expect(page.locator(".flash")).to_have_text("Organization name saved.")
    expect(page.locator(".org")).to_have_text("South Pier")
    expect(page.locator("#org-name")).to_have_value("South Pier")

    page.locator("#request-token").click()
    expect(page.locator(".flash")).to_have_text("New access token issued.")
    token = page.locator("#access-token").inner_text().strip()
    assert token
    expect(page.locator("#request-token")).to_have_text("Request a new access token")

    authorized = page.evaluate(
        """async (token) => {
            const response = await fetch("/api/contracts", {
                headers: {Authorization: "Bearer " + token}
            });
            return response.status;
        }""",
        token,
    )
    anonymous = page.evaluate("async () => (await fetch('/api/contracts')).status")
    assert authorized == 200
    assert anonymous == 401


def test_verifier_page_lists_fields_and_saves_edits(page: Page, base_url: str):
    _sign_in(page, base_url)
    page.locator("nav").get_by_role("link", name="Verifiers").click()
    expect(page.get_by_role("heading", name="Verifiers")).to_be_visible()

    row = page.locator(f"tr[data-verifier-name='{ACTIVE_VERIFIER}']")
    expect(row).to_have_attribute("data-active", "yes")
    expect(row).to_contain_text("1")
    expect(row).to_contain_text(SCHEMA_TRIGGER)
    row.get_by_role("link", name=ACTIVE_VERIFIER).click()

    expect(page.locator("#verifier-name")).to_have_value(ACTIVE_VERIFIER)
    expect(page.locator("#verifier-version")).to_have_value("1")
    expect(page.locator("#verifier-active")).to_have_value("true")
    expect(page.locator("#verifier-trigger")).to_have_value(SCHEMA_TRIGGER)
    expect(page.get_by_role("link", name=ACTIVE_CONTRACT)).to_be_visible()
    expect(page.get_by_text(format_timestamp(ACTIVE_VERIFIED_AT))).to_be_visible()

    page.locator("#verifier-name").fill("Payload schema")
    page.locator("#verifier-version").fill("4")
    page.locator("#verifier-active").select_option("false")
    page.locator("#verifier-trigger").fill("gitlab:payload-schema")
    page.locator("#save-verifier").click()

    expect(page.locator(".flash")).to_have_text("Verifier saved.")
    expect(page.locator("#verifier-name")).to_have_value("Payload schema")
    expect(page.locator("#verifier-version")).to_have_value("4")
    expect(page.locator("#verifier-active")).to_have_value("false")
    expect(page.locator("#verifier-trigger")).to_have_value("gitlab:payload-schema")

    page.locator("nav").get_by_role("link", name="Verifiers").click()
    expect(page.locator("tr[data-verifier-name='Payload schema']")).to_have_attribute("data-active", "no")
    expect(page.locator("tr[data-verifier-name='Payload schema']")).to_contain_text("gitlab:payload-schema")


def test_log_out_returns_to_the_login_page(page: Page, base_url: str):
    _sign_in(page, base_url)
    page.get_by_role("button", name="Log out").click()
    expect(page).to_have_url(re.compile(r"/login$"))
    page.goto(base_url + "/organization")
    expect(page.locator("#login-submit")).to_be_visible()


def test_statement_details_stay_readable_on_a_narrow_screen(page: Page, base_url: str):
    page.set_viewport_size({"width": 390, "height": 844})
    _sign_in(page, base_url)
    page.get_by_role("link", name=INACTIVE_CONTRACT).click()

    expect(page.locator("#statements thead")).to_be_hidden()
    expect(page.locator("#active-verifiers-empty")).to_be_visible()
    expect(page.locator("#statements")).to_contain_text(f"{DOCK_VERIFIER} v3 · Not verified")


def _sign_in(page: Page, base_url: str, username: str = "admin", password: str = "admin") -> None:
    page.goto(base_url + "/login")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#login-submit").click()


def _launch_browser(playwright):
    failures: list[str] = []
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(channel=channel, headless=True)
        except Exception as exc:
            failures.append(f"{channel}: {exc}")
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        failures.append(f"chromium: {exc}")
    detail = "\n".join(failures)
    raise RuntimeError(f"Could not launch a browser for UI tests.\n{detail}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(server: uvicorn.Server, url: str) -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        if server.started:
            try:
                httpx.get(url + "/login", timeout=0.5)
                return
            except httpx.HTTPError:
                pass
        time.sleep(0.05)
    raise RuntimeError("Contract Tester did not start for UI tests")
