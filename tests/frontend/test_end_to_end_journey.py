"""One real-browser, real-backend Atlas journey.

This is intentionally a black-box test: Selenium drives the product and the
small ``browser_http`` helper uses same-origin ``fetch`` only to reread the
documented HTTP resources and their response headers.  It never imports the
application, talks to MongoDB, or installs a mock server.
"""
from __future__ import annotations

import json
import os
import re

import pytest
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

from .conftest import registered_admin, submit_form, unique_username, wait_for


def browser_http(driver, path: str, method: str = "GET", body=None, key: str | None = None):
    """Perform one same-origin HTTP request from the real browser context."""
    script = """
      const [path, method, body, key, done] = arguments;
      const headers = {Accept: 'application/json'};
      if (body !== null) headers['Content-Type'] = 'application/json';
      if (key) headers['Idempotency-Key'] = key;
      fetch(path, {method, credentials: 'include', headers,
                  body: body === null ? undefined : JSON.stringify(body)})
        .then(async response => {
          const text = await response.text();
          let parsed = null;
          try { parsed = text ? JSON.parse(text) : null; } catch (_) {}
          done({status: response.status, requestId: response.headers.get('X-Request-ID'),
                body: parsed, text});
        })
        .catch(error => done({status: 0, requestId: null, body: null, text: String(error)}));
    """
    result = driver.execute_async_script(script, path, method, body, key)
    assert result["status"] != 0, f"browser HTTP failed: {result['text']}"
    assert result["requestId"], f"{method} {path} did not return X-Request-ID"
    return result


@pytest.mark.selenium
def test_registration_success_live_region_is_stable(browser, registered_admin):
    """Regression: submit the form, not the identically-labelled auth tab."""
    # The session fixture performs the one browser registration, after the
    # member/outsider provisions and before any later authenticated route.
    user = registered_admin
    success = browser.find_element(By.CSS_SELECTOR, ".success[role='status']")
    assert success.is_displayed()
    assert success.text == f"Account {user['username']} created. Sign in to continue."
    # The response acknowledgement is rendered before checking the global
    # live region; this avoids racing the form redraw while retaining both
    # assertions about the browser-visible success behavior.
    wait_for(browser, EC.text_to_be_present_in_element((By.ID, "status"), "created"))
    assert browser.find_element(By.ID, "status").get_attribute("role") == "status"
    assert browser.find_element(By.ID, "status").get_attribute("aria-live") == "polite"


@pytest.mark.selenium
def test_complete_real_backend_browser_journey(atlas_browser, registered_admin):
    """Cover every client route and lifecycle in one isolated, reread-verified journey."""
    browser, base_url = atlas_browser
    users = json.loads(os.environ["ATLAS_TEST_USERS"])
    member_username = users["member"]["username"]
    member_password = users["member"]["password"]
    outsider = users["outsider"]

    admin = registered_admin
    browser.get(f"{base_url}/")
    assert browser.title == "Atlas Pools"
    assert browser.find_element(By.ID, "app").get_attribute("tabindex") == "-1"
    assert browser_http(browser, "/healthz")["status"] == 200
    assert browser_http(browser, "/readyz")["status"] in (200, 503)

    # Username/password registration, login, auth/me, empty state, keyboard/focus,
    # and cookie session.
    browser.get(f"{base_url}/#/signin")
    wait_for(browser, EC.presence_of_element_located((By.NAME, "username")))
    submit_form(browser, admin, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    me = browser_http(browser, "/auth/me")
    assert me["status"] == 200 and me["body"]
    assert "No groups yet" in browser.find_element(By.TAG_NAME, "main").text
    group_name = "<img>alert(1)</img>"
    # Submit the group form itself.  A keyboard TAB assertion here was coupled
    # to the page's incidental focus order and could submit the wrong control
    # while the groups request was still being rendered.
    create_group = browser.find_element(By.ID, "create-group-form")
    create_group.find_element(By.CSS_SELECTOR, "input[name='name']").send_keys(group_name)
    create_group.find_element(By.XPATH, ".//button[@type='submit']").click()
    try:
        wait_for(browser, EC.url_matches(r".*#/groups/[^/]+$"))
    except TimeoutException:
        errors = browser.find_elements(By.CSS_SELECTOR, "#app .error[role='alert']")
        detail = errors[0].text if errors else "No browser-visible API error was rendered."
        pytest.fail(f"group creation did not navigate to a group route: {detail}")
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//main//h2")))
    group_id = browser.current_url.split("/groups/", 1)[1].split("/", 1)[0]
    assert group_name in browser.find_element(By.TAG_NAME, "main").text

    group = browser_http(browser, f"/v1/pool-groups/{group_id}")
    assert group["status"] == 200 and group["body"]["id"] == group_id
    if str(me["body"].get("id")) != str(group["body"].get("admin_user_id")):
        pytest.fail(
            "BACKEND MISMATCH: /auth/me.id does not equal "
            f"/v1/pool-groups/{group_id}.admin_user_id "
            f"({me['body'].get('id')!r} != {group['body'].get('admin_user_id')!r})"
        )
    # Regression: the authenticated creator receives the member-management
    # affordance when the documented identity values match.
    wait_for(browser, EC.presence_of_element_located((By.ID, "add-member-form")))
    assert browser.find_element(By.ID, "add-member-submit").is_displayed()
    listed = browser_http(browser, "/v1/pool-groups")
    assert any(item["id"] == group_id for item in (listed["body"].get("items", listed["body"])))

    invalid = browser_http(browser, "/v1/pool-groups", "POST", {"name": ""}, unique_username("validation-key"))
    assert invalid["status"] == 422 and invalid["body"]["error"]["code"] == "VALIDATION_ERROR"

    # A separately registered outsider must not discover this group.
    browser.find_element(By.XPATH, "//button[normalize-space()='Sign out']").click()
    wait_for(browser, EC.url_contains("#/signin"))
    submit_form(browser, outsider, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    outsider_view = browser_http(browser, f"/v1/pool-groups/{group_id}")
    assert outsider_view["status"] == 404
    browser.find_element(By.XPATH, "//button[normalize-space()='Sign out']").click()
    wait_for(browser, EC.url_contains("#/signin"))
    submit_form(browser, admin, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    browser.get(f"{base_url}/#/groups/{group_id}")
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//main//h2")))
    wait_for(browser, EC.presence_of_element_located((By.ID, "add-member-form")))

    # Idempotent mutation: the same key must reconcile to one server resource.
    idem_key = f"journey-{unique_username('idempotency')}"
    idem_body = {"name": f"idempotent-{unique_username('group')}"}
    first = browser_http(browser, "/v1/pool-groups", "POST", idem_body, idem_key)
    second = browser_http(browser, "/v1/pool-groups", "POST", idem_body, idem_key)
    assert first["status"] == 201 and second["status"] in (200, 201)
    assert first["body"]["id"] == second["body"]["id"]

    # Members: add/remove, server reread, and opaque-cursor pagination.
    add = browser.find_element(By.NAME, "username")
    assert add.get_attribute("type") == "text"
    add.send_keys(member_username)
    browser.find_element(By.XPATH, "//button[normalize-space()='Add member']").click()
    try:
        wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), member_username))
    except TimeoutException:
        alerts = []
        for alert in browser.find_elements(By.CSS_SELECTOR, ".error[role='alert']"):
            if not alert.is_displayed():
                continue
            text = alert.text
            request_id_match = re.search(r"Request ID:\s*(\S+)", text)
            alerts.append({
                "text": text,
                "request_id": request_id_match.group(1) if request_id_match else None,
            })
        pytest.fail(
            "member add did not render the registered username; "
            f"browser-visible alerts={alerts!r}; "
            f"current page HTML={browser.page_source}"
        )
    members = browser_http(browser, f"/v1/pool-groups/{group_id}/members?limit=1")
    assert members["status"] == 200 and members["body"].get("items")
    if not members["body"].get("next_cursor"):
        pytest.fail("BLOCKED: fixture must provide enough members for cursor pagination")
    next_page = browser_http(browser, f"/v1/pool-groups/{group_id}/members?limit=1&cursor={members['body']['next_cursor']}")
    assert next_page["status"] == 200
    page_members = members["body"]["items"] + next_page["body"]["items"]
    assert sum(item.get("username") == member_username for item in page_members) == 1
    browser.refresh()
    wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), member_username))
    # Keep this member active through the closed/late-answer checks; removal is
    # performed in the cleanup section after the member session has been used.

    # Draft validation (422-shaped UI validation), edit, open, and answered state.
    browser.find_element(By.NAME, "question").send_keys("Journey question")
    browser.find_element(By.NAME, "options").send_keys("Alpha\nBeta")
    browser.find_element(By.XPATH, "//button[normalize-space()='Create draft']").click()
    wait_for(browser, EC.url_contains("/pools/"))
    pool_id = browser.current_url.rsplit("/", 1)[1]
    assert "Status: draft" in browser.find_element(By.TAG_NAME, "main").text
    browser.find_element(By.NAME, "question").clear()
    browser.find_element(By.NAME, "question").send_keys("Journey question edited")
    browser.find_element(By.XPATH, "//button[normalize-space()='Save draft']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.ID, "status"), "Draft saved"))
    browser.find_element(By.XPATH, "//button[normalize-space()='Open pool']").click()
    try:
        wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), "Status: open"))
    except TimeoutException:
        alerts = []
        for alert in browser.find_elements(By.CSS_SELECTOR, "[role='alert']"):
            if not alert.is_displayed():
                continue
            text = alert.text
            request_id_match = re.search(r"Request ID:\s*(\S+)", text)
            alerts.append({
                "text": text,
                "request_id": request_id_match.group(1) if request_id_match else None,
            })
        try:
            current_pool = browser_http(browser, f"/v1/pool-groups/{group_id}/pools/{pool_id}")
            current_pool_status = {
                "http_status": current_pool["status"],
                "request_id": current_pool["requestId"],
                "body_status": (
                    current_pool["body"].get("status")
                    if isinstance(current_pool.get("body"), dict)
                    else None
                ),
                "body": current_pool["body"],
            }
        except (AssertionError, KeyError, TypeError) as error:
            current_pool_status = f"GET failed while collecting status: {error}"
        pytest.fail(
            "Open pool did not render Status: open; "
            "the visible alert text/request ID identifies the POST failure (409/422/500), "
            "while the reread identifies an invalid response shape or a draft that remained open; "
            f"visible alerts={alerts!r}; "
            f"current pool status={current_pool_status!r}; "
            f"current page HTML={browser.page_source}"
        )
    assert "Status: open" in browser.find_element(By.TAG_NAME, "main").text
    assert not browser.find_elements(By.XPATH, "//button[normalize-space()='Save draft']")
    pool_list = browser_http(browser, f"/v1/pool-groups/{group_id}/pools")
    assert pool_list["status"] == 200 and any(item["id"] == pool_id for item in pool_list["body"].get("items", pool_list["body"]))
    pool = browser_http(browser, f"/v1/pool-groups/{group_id}/pools/{pool_id}")
    assert pool["status"] == 200 and pool["body"]["status"] == "open"

    pool_url = browser.current_url
    admin_tab = browser.current_window_handle
    browser.switch_to.new_window("tab")
    browser.get(pool_url)
    wait_for(browser, EC.presence_of_element_located((By.XPATH, "//input[@type='radio']")))
    browser.find_element(By.XPATH, "//input[@type='radio']").click()
    browser.find_element(By.XPATH, "//button[normalize-space()='Submit answer']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.ID, "status"), "Answer submitted"))
    assert not browser.find_elements(By.XPATH, "//button[normalize-space()='Submit answer']")
    # A duplicate click / reread gets the server 409 contract and remains disabled.
    duplicate = browser_http(browser, f"/v1/pool-groups/{group_id}/pools/{pool_id}/answers", "POST", {"option_id": pool["body"]["options"][0]["id"]}, unique_username("duplicate-key"))
    assert duplicate["status"] == 409 and duplicate["body"]["error"]["code"] == "POOL_ALREADY_ANSWERED"
    browser.close()
    browser.switch_to.window(admin_tab)
    browser.find_element(By.XPATH, "//button[normalize-space()='Close pool']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), "Closed results"))
    closed = browser_http(browser, f"/v1/pool-groups/{group_id}/pools/{pool_id}/results")
    assert closed["status"] == 200
    assert not any(key in json.dumps(closed["body"]).lower() for key in ("respondent", "user_id", "email"))
    assert browser.find_element(By.TAG_NAME, "main").get_attribute("innerHTML").count("<script") == 0

    # Member session proves 403 and late answer; closed result is readable only now.
    browser.find_element(By.XPATH, "//button[normalize-space()='Sign out']").click()
    wait_for(browser, EC.url_contains("#/signin"))
    submit_form(browser, {"username": member_username, "password": member_password}, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    forbidden = browser_http(browser, f"/v1/pool-groups/{group_id}/pools", "POST", {"question": "no", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}, unique_username("forbidden-key"))
    assert forbidden["status"] == 403
    late = browser_http(browser, f"/v1/pool-groups/{group_id}/pools/{pool_id}/answers", "POST", {"option_id": pool["body"]["options"][0]["id"]}, unique_username("late-key"))
    assert late["status"] == 409 and late["body"]["error"]["code"] in {"POOL_NOT_OPEN", "POOL_ALREADY_ANSWERED"}

    # Return to the isolated admin account and exercise the destructive member
    # control before revoking the final session.
    browser.find_element(By.XPATH, "//button[normalize-space()='Sign out']").click()
    wait_for(browser, EC.url_contains("#/signin"))
    submit_form(browser, admin, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    browser.get(f"{base_url}/#/groups/{group_id}")
    wait_for(browser, EC.presence_of_element_located((By.XPATH, f"//tr[.//*[normalize-space()='{member_username}']]")))
    browser.find_element(By.XPATH, f"//tr[.//*[normalize-space()='{member_username}']]//button[normalize-space()='Remove']").click()
    wait_for(browser, EC.text_to_be_present_in_element((By.ID, "status"), "Member removed"))

    browser.get(f"{base_url}/#/groups/00000000-0000-4000-8000-000000000000")
    wait_for(browser, EC.text_to_be_present_in_element((By.TAG_NAME, "main"), "unavailable"))
    assert browser.find_element(By.TAG_NAME, "body").get_attribute("innerHTML").count("<img") == 0

    # 401/session expiry (the inaccessible 404 route was checked above).
    browser.delete_all_cookies()
    expired = browser_http(browser, "/auth/me")
    assert expired["status"] == 401 and expired["body"]["error"]["code"] == "AUTHENTICATION_REQUIRED"
    browser.get(f"{base_url}/#/groups")
    wait_for(browser, EC.url_contains("#/signin"))
