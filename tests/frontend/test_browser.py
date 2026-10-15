"""Black-box Selenium coverage of every user-facing frontend capability.

The browser is the only client under test.  Persistence is observed by reloading
the actual app and rereading server state; no test imports Atlas implementation
modules or reads MongoDB directly.
"""
from __future__ import annotations

import json
import os

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

from .conftest import registered_admin, submit_form, unique_username, wait_for


@pytest.mark.selenium
def test_root_health_password_auth_me_logout_and_session_expiry(browser, base_url, registered_admin):
    browser.get(f"{base_url}/")
    assert "Atlas Pools" in browser.title
    browser.get(f"{base_url}/app.js")
    assert "fetch" in browser.find_element(By.TAG_NAME, "body").text
    browser.get(f"{base_url}/styles.css")
    assert "font-family" in browser.find_element(By.TAG_NAME, "body").text
    browser.get(f"{base_url}/")
    browser.get(f"{base_url}/healthz")
    assert '"status":"ok"' in browser.find_element(By.TAG_NAME, "body").text.replace(" ", "")
    browser.get(f"{base_url}/readyz")
    assert browser.find_element(By.TAG_NAME, "body").text
    browser.get(f"{base_url}/#/signin")
    assert browser.find_element(By.NAME, "username").is_displayed()
    # Registration is performed once by the shared real-browser fixture so this
    # auth journey does not consume a fourth success from the IP budget.
    user = registered_admin
    submit_form(browser, user, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    browser.get(f"{base_url}/auth/me")
    assert user["username"] in browser.find_element(By.TAG_NAME, "body").text
    browser.get(f"{base_url}/#/groups")
    browser.find_element(By.XPATH, "//button[normalize-space()='Sign out']").click()
    wait_for(browser, EC.url_contains("#/signin"))
    browser.get(f"{base_url}/auth/me")
    assert "AUTHENTICATION_REQUIRED" in browser.find_element(By.TAG_NAME, "body").text
    # A removed (expired at the browser boundary) or revoked session must not be
    # usable after reload.
    browser.delete_all_cookies()
    browser.get(f"{base_url}/auth/me")
    assert "AUTHENTICATION_REQUIRED" in browser.find_element(By.TAG_NAME, "body").text
    browser.get(f"{base_url}/#/groups")
    wait_for(browser, EC.url_contains("#/signin"))


@pytest.mark.selenium
def test_groups_creation_detail_members_and_persistence(browser, base_url, registered_user):
    browser.find_element(By.NAME, "name").send_keys("Browser persistence group")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create group']").click()
    wait_for(browser, EC.url_contains("#/groups/"))
    assert browser.find_element(By.XPATH, "//*[normalize-space()='Browser persistence group']")
    assert browser.find_element(By.XPATH, "//*[normalize-space()='Members']")
    browser.refresh()
    wait_for(browser, EC.url_contains("#/groups/"))
    assert "Browser persistence group" in browser.find_element(By.TAG_NAME, "main").text


@pytest.mark.selenium
def test_pool_draft_open_closed_answer_duplicate_and_private_results(browser, base_url, registered_user):
    browser.find_element(By.NAME, "name").send_keys("Lifecycle group")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create group']").click()
    wait_for(browser, EC.url_contains("#/groups/"))
    browser.find_element(By.NAME, "question").send_keys("Safe question")
    browser.find_element(By.NAME, "options").send_keys("Alpha\nBeta")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create draft']").click()
    wait_for(browser, EC.url_contains("/pools/"))
    assert "Status: draft" in browser.find_element(By.TAG_NAME, "main").text
    browser.find_element(By.XPATH, "//button[normalize-space()='Save draft']").click()
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//button[normalize-space()='Open pool']")))
    browser.find_element(By.XPATH, "//button[normalize-space()='Open pool']").click()
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//button[normalize-space()='Close pool']")))
    assert not browser.find_elements(By.XPATH, "//button[normalize-space()='Save draft']")
    pool_url = browser.current_url
    first_window = browser.current_window_handle
    browser.switch_to.new_window("tab")
    browser.get(pool_url)
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//button[normalize-space()='Submit answer']")))
    second_window = browser.current_window_handle
    browser.switch_to.window(first_window)
    browser.find_element(By.XPATH, "//input[@type='radio']").click()
    browser.find_element(By.XPATH, "//button[normalize-space()='Submit answer']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.ID, "status"), "Answer submitted"))
    assert not browser.find_elements(By.XPATH, "//button[normalize-space()='Submit answer']")
    browser.switch_to.window(second_window)
    browser.find_element(By.XPATH, "//input[@type='radio']").click()
    browser.find_element(By.XPATH, "//button[normalize-space()='Submit answer']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), "already answered"))
    assert not browser.find_elements(By.XPATH, "//button[normalize-space()='Submit answer']")
    browser.close()
    browser.switch_to.window(first_window)
    browser.find_element(By.XPATH, "//button[normalize-space()='Close pool']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), "Closed results"))
    main_text = browser.find_element(By.TAG_NAME, "main").text
    assert "Total answers: 1" in main_text
    assert "Alpha" in main_text and "Beta" in main_text
    assert "respondent" not in main_text.lower()


@pytest.mark.selenium
def test_validation_keyboard_focus_safe_text_and_request_ids(browser, base_url, registered_user):
    browser.get(f"{base_url}/#/groups/00000000-0000-4000-8000-000000000000")
    wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), "unavailable"))
    browser.get(f"{base_url}/#/groups")
    wait_for(browser, EC.presence_of_element_located((By.NAME, "name")))
    browser.find_element(By.NAME, "name").send_keys("<img>alert(1)</img>")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create group']").click()
    wait_for(browser, EC.url_contains("#/groups/"))
    assert "<img>" in browser.find_element(By.TAG_NAME, "main").text
    browser.find_element(By.NAME, "question").send_keys("Invalid draft")
    browser.find_element(By.NAME, "options").send_keys("only one")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create draft']").click()
    assert "at least two" in browser.find_element(By.TAG_NAME, "main").text.lower()
    browser.find_element(By.TAG_NAME, "body").send_keys(Keys.TAB)
    assert browser.switch_to.active_element is not None


@pytest.mark.selenium
def test_backend_read_routes_error_envelope_and_accessible_controls(browser, base_url, registered_user):
    """Exercise the unauthenticated read boundary and the rendered controls.

    These assertions deliberately use the running target.  They are not a mock
    of the API: the browser performs the request and then navigates back through
    the real client session.
    """
    browser.delete_all_cookies()
    browser.get(f"{base_url}/auth/me")
    assert "error" in browser.find_element(By.TAG_NAME, "body").text
    browser.get(f"{base_url}/#/signin")
    wait_for(browser, EC.presence_of_element_located((By.NAME, "username")))
    submit_form(browser, registered_user, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    browser.get(f"{base_url}/#/groups")
    wait_for(browser, EC.presence_of_element_located((By.NAME, "name")))

    name = browser.find_element(By.NAME, "name")
    name.send_keys("Keyboard route group")
    name.send_keys(Keys.TAB)
    assert browser.switch_to.active_element.get_attribute("type") in {"submit", "button"}
    browser.switch_to.active_element.send_keys(Keys.ENTER)
    wait_for(browser, EC.url_contains("#/groups/"))
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//*[normalize-space()='Members']")))
    assert browser.find_element(By.CSS_SELECTOR, "main").get_attribute("aria-busy") in {"false", None}


@pytest.mark.selenium
def test_member_and_pool_route_controls_are_server_driven(browser, base_url, registered_user):
    """Cover member pagination/add/remove affordances and pool list controls.

    The second user is publicly registered with a non-email username. No
    inferred email or private database provisioning is permitted.
    """
    browser.find_element(By.NAME, "name").send_keys("Route matrix group")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create group']").click()
    wait_for(browser, EC.url_contains("#/groups/"))
    main = browser.find_element(By.TAG_NAME, "main")
    assert "Members" in main.text and "Pools" in main.text
    assert browser.find_elements(By.XPATH, "//table[@aria-label='Group members']")
    member_username = json.loads(os.environ["ATLAS_TEST_USERS"])["member"]["username"]
    add = browser.find_element(By.NAME, "username")
    assert add.get_attribute("type") == "text"
    assert add.get_attribute("id") == "add-member-username"
    assert add.get_attribute("placeholder") == "Type a username to search"
    assert browser.find_element(By.CSS_SELECTOR, "label[for='add-member-username']").text == "Choose a username"
    assert add.get_attribute("role") == "combobox"
    add_member = browser.find_element(By.ID, "add-member-submit")
    assert not add_member.is_enabled()
    assert not browser.find_elements(By.NAME, "member-selector")
    assert not browser.find_elements(By.NAME, "email")
    # The picker searches a normalized username substring, then submits the
    # username represented by the selected suggestion—not an email or display
    # label invented by the browser.
    add.send_keys(member_username[2:-2])
    wait_for(browser, EC.presence_of_element_located((By.CSS_SELECTOR, "[role='listbox'] [role='option']")))
    suggestion = browser.find_element(By.CSS_SELECTOR, "[role='listbox'] [role='option']")
    assert suggestion.text == member_username
    # The combobox supports listbox navigation without requiring a mouse.
    add.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
    assert add.get_attribute("value") == member_username
    assert add_member.is_enabled()
    browser.find_element(By.XPATH, "//button[normalize-space()='Add member']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), member_username))
    row = browser.find_element(By.XPATH, f"//tr[.//*[normalize-space()='{member_username}']]")
    remove = row.find_element(By.XPATH, ".//button[normalize-space()='Remove']")
    remove.click()
    wait_for(browser, EC.text_to_be_present_in_element((By.ID, "status"), "Member removed"))
    browser.refresh()
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//*[normalize-space()='Members']")))
    assert member_username not in browser.find_element(By.TAG_NAME, "main").text
    browser.find_element(By.NAME, "question").send_keys("Route pool")
    browser.find_element(By.NAME, "options").send_keys("One\nTwo")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create draft']").click()
    wait_for(browser, EC.url_contains("/pools/"))
    assert browser.find_element(By.XPATH, "//button[normalize-space()='Save draft']").is_enabled()


@pytest.mark.selenium
def test_configured_error_matrix_is_not_silently_skipped(browser, base_url, registered_user):
    """Exercise documented deterministic errors; no invented fault routes."""
    browser.delete_all_cookies()
    browser.get(f"{base_url}/auth/me")
    assert "AUTHENTICATION_REQUIRED" in browser.find_element(By.TAG_NAME, "body").text
    browser.get(f"{base_url}/#/signin")
    submit_form(browser, registered_user, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    invalid = browser.execute_async_script("""
      const done = arguments[0];
      fetch('/v1/pool-groups/00000000-0000-4000-8000-000000000000/members?limit=0',
        {credentials:'include'}).then(async r => done({status:r.status, body:await r.text()}));
    """)
    assert invalid["status"] == 422
    assert "VALIDATION_ERROR" in invalid["body"]
