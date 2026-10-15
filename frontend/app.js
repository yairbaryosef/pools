/* Atlas browser client. Identity, authorization, lifecycle, and cookie state belong to the server. */
const API = "/v1";
const app = document.querySelector("#app");
const status = document.querySelector("#status");
const sessionControls = document.querySelector("#session-controls");
let currentUser = null;

const el = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};
const announce = (message = "") => { status.textContent = message; };
const requestKey = () => crypto.randomUUID();
const pathPart = value => encodeURIComponent(String(value));
const itemsOf = value => Array.isArray(value) ? value : (value?.items || []);
// The documented user shape uses id.  _id is accepted only as a compatibility
// read for older password-session responses; authorization remains server-owned.
const identityValue = value => value === null || value === undefined ? "" : String(value);
const sameIdentity = (left, right) => identityValue(left) !== "" && identityValue(left) === identityValue(right);
const isCurrentAdmin = group =>
  sameIdentity(currentUser?.id ?? currentUser?._id, group?.admin_user_id);

function formField(labelText, type, name, required = true) {
  const wrap = el("div");
  const label = el("label", labelText);
  const input = el(type === "textarea" ? "textarea" : "input");
  input.name = name;
  input.id = name;
  input.required = required;
  input.autocomplete = name === "password" ? "current-password" : name;
  if (type !== "textarea") input.type = type;
  label.htmlFor = name;
  wrap.append(label, input);
  return wrap;
}

function friendlyError(statusCode, code) {
  if (statusCode === 401) return "Your session has expired. Please sign in again.";
  if (statusCode === 403) return "You do not have permission to do that.";
  if (statusCode === 404) return "That resource is unavailable.";
  if (statusCode === 409) {
    if (code === "POOL_ALREADY_ANSWERED") return "You have already answered this pool.";
    if (code === "POOL_NOT_OPEN") return "This pool is not accepting answers.";
    if (code === "POOL_NOT_CLOSED") return "Results are available after the pool is closed.";
    if (code === "INVALID_POOL_TRANSITION") return "That pool lifecycle change is no longer available.";
    return "The requested change conflicts with the current server state.";
  }
  if (statusCode === 422) return "Check the highlighted information and try again.";
  if (statusCode === 429) return "Too many requests. Wait a moment and try again.";
  if (statusCode >= 500) return "The service is temporarily unavailable.";
  return "The request could not be completed.";
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = new Headers(options.headers || {});
  // Keep the client-only retry key out of RequestInit.  It is transport
  // metadata, not a browser credential or application payload.
  const { idempotencyKey, expectedStatus, body: rawBody, ...requestOptions } = options;
  const isFormData = typeof FormData !== "undefined" && rawBody instanceof FormData;
  const isBlob = typeof Blob !== "undefined" && rawBody instanceof Blob;
  // Fetch does not serialize objects. Normalize JSON objects here while
  // retaining native body types and already-serialized JSON strings.
  const requestBody = rawBody !== null && typeof rawBody === "object" && !isFormData && !isBlob
    ? JSON.stringify(rawBody)
    : rawBody;
  headers.set("Accept", "application/json");
  if (rawBody !== undefined && !isFormData && !isBlob) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD"].includes(method)) headers.set("Idempotency-Key", idempotencyKey || requestKey());
  // Accept both documented absolute API paths and route-relative paths.  This
  // keeps the wire URL unambiguous when debugging a live deployment: a caller
  // passing /v1/... must never become /v1/v1/....
  const prefix = path.startsWith("/auth/") || path.startsWith(`${API}/`) ? "" : API;
  let response;
  try {
    response = await fetch(`${prefix}${path}`, { ...requestOptions, body: requestBody, headers, credentials: "include" });
  } catch {
    throw { status: 0, code: "OFFLINE", message: "The service cannot be reached. Check your connection and try again." };
  }
  const requestId = response.headers.get("X-Request-ID") || "";
  let body = null;
  try { body = response.status === 204 ? null : await response.json(); } catch { /* Keep a safe generic error. */ }
  if (!response.ok) {
    const error = body?.error || {};
    const result = {
      status: response.status,
      code: error.code || `HTTP_${response.status}`,
      // Resource existence and membership are intentionally indistinguishable
      // to callers. Never expose a backend 404 message (which may contain
      // implementation details); retain the status, stable code, and request
      // ID for accessible diagnostics.
      message: response.status === 404
        ? friendlyError(response.status, error.code)
        : error.message || friendlyError(response.status, error.code),
      requestId: error.request_id || requestId,
    };
    if (response.status === 401) {
      currentUser = null;
      renderSession();
      if (location.hash !== "#/signin") location.hash = "#/signin";
    }
    throw result;
  }
  if (expectedStatus !== undefined && response.status !== expectedStatus) {
    throw {
      status: response.status,
      code: `UNEXPECTED_HTTP_${response.status}`,
      message: `The service returned HTTP ${response.status}; expected HTTP ${expectedStatus}.`,
      requestId,
    };
  }
  return { data: body, requestId, status: response.status };
}

function showError(container, error) {
  const details = [error.status ? `HTTP ${error.status}` : "", error.code || ""]
    .filter(Boolean).join(" ");
  const box = el("p", [error.message || "Something went wrong.", details].filter(Boolean).join(" ("));
  if (details) box.append(")");
  box.className = "error";
  box.setAttribute("role", "alert");
  box.tabIndex = -1;
  if (error.requestId) box.append(" Request ID: ", el("code", error.requestId));
  container.prepend(box);
  announce(box.textContent);
  // Move focus to the announced error without stealing focus from successful
  // controls during ordinary rendering.
  box.focus({ preventScroll: true });
}
function busy(form, value) {
  form.querySelectorAll("button, input, textarea").forEach(control => { control.disabled = value; });
  form.setAttribute("aria-busy", String(value));
}
function card(title) {
  const section = el("section");
  section.className = "card";
  section.append(el("h2", title));
  return section;
}
function link(text, href) { const anchor = el("a", text); anchor.href = href; return anchor; }
function setLoading(container, text = "Loading…") {
  container.setAttribute("aria-busy", "true");
  container.append(el("p", text));
}
function finishLoading(container) { container.setAttribute("aria-busy", "false"); }

function renderMemberImmediately(panel, member) {
  const body = panel.querySelector("tbody");
  if (!body) return;
  const userId = identityValue(member.user_id);
  const username = identityValue(member.username);
  const duplicate = [...body.rows].some(row =>
    userId && row.dataset.memberId === userId
  );
  if (duplicate) return;
  const row = el("tr");
  if (userId) row.dataset.memberId = userId;
  row.append(el("td", username || member.display_name || userId || "Member"), el("td", member.role || "member"), el("td", "—"));
  body.append(row);
}

function focusMain() {
  // Hash navigation replaces the view asynchronously; focusing the landmark
  // makes keyboard navigation deterministic and gives screen-reader users a
  // clear announcement point.
  app.focus({ preventScroll: true });
}

function renderSession() {
  sessionControls.replaceChildren();
  if (!currentUser) return;
  const identity = el("span", currentUser.username || currentUser.email || "Signed in");
  identity.className = "session-identity";
  sessionControls.append(identity);
  const button = el("button", "Sign out");
  button.className = "secondary";
  button.type = "button";
  button.onclick = async () => {
    button.disabled = true;
    try { await api("/auth/logout", { method: "POST" }); announce("Signed out."); }
    catch (error) { showError(app, error); }
    currentUser = null;
    renderSession();
    location.hash = "#/signin";
  };
  sessionControls.append(button);
}

async function loadSession() {
  try { currentUser = (await api("/auth/me")).data; }
  catch (error) { if (error.status !== 401 && error.status !== 0) announce(error.message); currentUser = null; }
  renderSession();
}

function authView() {
  app.replaceChildren();
  const section = card("Sign in to Atlas");
  section.classList.add("narrow");
  section.prepend(el("p", "Use your Atlas username and password. Your session is held in a secure, HttpOnly cookie."));
  const tabs = el("div");
  const signIn = el("button", "Sign in");
  const register = el("button", "Create account");
  signIn.type = register.type = "button";
  register.className = "secondary";
  tabs.append(signIn, register);
  section.append(tabs);
  const area = el("div");
  section.append(area);
  app.append(section);
  // Keep the registration acknowledgement in auth-view state.  Switching from
  // registration to sign-in redraws the form, so passing the message only to
  // the registration render would otherwise make it disappear immediately.
  let authNotice = "";
  const draw = (isRegister, notice = authNotice) => {
    area.replaceChildren();
    if (notice) {
      const success = el("p", notice);
      success.className = "success";
      success.setAttribute("role", "status");
      area.append(success);
    }
    const form = el("form");
    const username = formField("Username", "text", "username");
    username.querySelector("input").autocomplete = isRegister ? "username" : "username";
    const password = formField("Password", "password", "password");
    password.querySelector("input").autocomplete = isRegister ? "new-password" : "current-password";
    form.append(username, password);
    const submit = el("button", isRegister ? "Create account" : "Sign in");
    submit.type = "submit";
    form.append(submit);
    form.onsubmit = async event => {
      event.preventDefault();
      busy(form, true);
      try {
        const usernameValue = form.elements.username.value.trim();
        const passwordValue = form.elements.password.value;
        if (!usernameValue || !passwordValue) {
          showError(area, { message: "Enter both a username and password." });
          busy(form, false);
          return;
        }
        const result = await api(`/auth/${isRegister ? "register" : "login"}`, {
          method: "POST",
          body: JSON.stringify({ username: usernameValue, password: passwordValue }),
        });
        if (isRegister) {
          // Auth endpoints return the public user directly.  Accepting a
          // `user` member as well keeps the client tolerant of the equivalent
          // envelope used by local development targets without treating either
          // response as an authorization decision.
          const registeredUser = result.data?.user || result.data;
          const accountName = registeredUser?.username || usernameValue;
          const message = `Account ${accountName} created. Sign in to continue.`;
          authNotice = message;
          draw(false);
          // Update the live region after the auth form has been replaced.  This
          // keeps the persistent acknowledgement and the announcement in the
          // same committed UI update, which is reliably observed by browsers
          // and assistive technology after a network response.
          announce(message);
        }
        else {
          // Login establishes the HttpOnly cookie on the response.  The
          // request helper always uses credentials: "include", including on
          // http:// local targets, so the browser owns and sends that cookie.
          currentUser = result.data?.user || result.data;
          authNotice = "";
          announce("Signed in.");
          renderSession();
          location.hash = "#/groups";
        }
      } catch (error) { showError(area, error); busy(form, false); }
    };
    area.append(form);
  };
  signIn.onclick = () => draw(false);
  register.onclick = () => draw(true);
  draw(false);
}

async function groupsView() {
  app.replaceChildren();
   const section = card("My groups");
   section.append(el("p", "Groups where you have active membership."));
   const form = el("form");
   form.id = "create-group-form";
   const nameField = formField("New group name", "text", "name");
   const nameInput = nameField.querySelector("input[name='name']");
   nameInput.id = "create-group-name";
   nameField.querySelector("label").htmlFor = nameInput.id;
   form.append(nameField);
  const create = el("button", "Create group");
  create.type = "submit";
  form.append(create);
  form.onsubmit = async event => {
    event.preventDefault(); busy(form, true);
    try {
       const name = nameInput.value.trim();
      if (!name) { showError(section, { message: "Enter a group name." }); busy(form, false); return; }
       const result = await api("/pool-groups", {
         method: "POST",
         body: JSON.stringify({ name }),
         expectedStatus: 201,
       });
       // POST /v1/pool-groups returns the group resource directly, not an
       // envelope.  Do not derive the route from the submitted name or from
       // the list request; reconcile navigation with the created resource.
       const group = result.data;
       if (!group || typeof group !== "object" || !group.id) {
         throw {
           status: result.status,
           code: "INVALID_GROUP_RESPONSE",
           message: "The service created the group but returned no group ID.",
           requestId: result.requestId,
         };
       }
       location.hash = `#/groups/${pathPart(group.id)}`;
    }
    catch (error) { showError(section, error); busy(form, false); }
  };
  section.append(form);
  const list = el("div"); setLoading(list, "Loading groups…"); section.append(list); app.append(section);
  try {
    const groups = itemsOf((await api("/pool-groups")).data);
    list.replaceChildren(); finishLoading(list);
    if (!groups.length) list.append(el("p", "No groups yet. Create one above."));
    groups.forEach(group => { const item = el("article"); item.className = "card"; item.append(link(group.name || "Unnamed group", `#/groups/${pathPart(group.id)}`), el("p", `${group.member_count ?? 0} member(s)`)); list.append(item); });
  } catch (error) { list.replaceChildren(); finishLoading(list); showError(list, error); }
}

async function groupView(groupId, memberCursor = null, optimisticMember = null) {
  app.replaceChildren();
  const section = card("Group"); setLoading(section, "Loading group…"); app.append(section);
  const id = pathPart(groupId);
  try {
    const group = (await api(`/pool-groups/${id}`)).data;
    section.replaceChildren(el("h2", group.name || "Group"));
     const members = card("Members");
     members.id = "group-members-panel";
     let memberPage = (await api(`/pool-groups/${id}/members?limit=25${memberCursor ? `&cursor=${encodeURIComponent(memberCursor)}` : ""}`)).data;
     const memberList = itemsOf(memberPage).map(member => ({ ...member }));
      // Some server responses return only the membership shape from the POST.
      // Keep the selected username attached while the authoritative list is
      // reread, without inventing any identity fields in the browser.
      if (optimisticMember) {
        const existing = memberList.find(member =>
          (optimisticMember.user_id && sameIdentity(member.user_id, optimisticMember.user_id)) ||
          (optimisticMember.username && member.username === optimisticMember.username)
        );
        if (existing) {
          if (!existing.username && optimisticMember.username) existing.username = optimisticMember.username;
        } else {
         memberList.push(optimisticMember);
       }
     }
    if (!memberList.length) members.append(el("p", "No members found."));
     else {
        const table = el("table"); table.setAttribute("aria-label", "Group members"); const head = el("tr"); ["User", "Role", "Actions"].forEach(value => { const th = el("th", value); th.scope = "col"; head.append(th); }); const thead = el("thead"); thead.append(head); table.append(thead); const body = el("tbody");
        memberList.forEach(member => {
          const row = el("tr");
          if (member.user_id) row.dataset.memberId = identityValue(member.user_id);
            row.append(el("td", member.username || member.display_name || member.user_id || "Member"), el("td", member.role || "member"));
         const actions = el("td");
            if (isCurrentAdmin(group) && !sameIdentity(member.user_id, group.admin_user_id)) {
            const remove = el("button", "Remove"); remove.type = "button"; remove.className = "danger"; remove.id = `remove-member-${identityValue(member.user_id)}`; remove.setAttribute("aria-label", `Remove member ${member.user_id}`);
           remove.onclick = async () => { remove.disabled = true; try { await api(`/pool-groups/${id}/members/${pathPart(member.user_id)}`, { method: "DELETE" }); announce("Member removed."); await groupView(groupId); } catch (error) { showError(members, error); remove.disabled = false; } };
           actions.append(remove);
         } else actions.append(el("span", "—"));
         row.append(actions); body.append(row);
       }); table.append(body); members.append(table);
       if (memberPage.next_cursor) { const more = el("button", "Next members"); more.type = "button"; more.className = "secondary"; more.onclick = async () => { more.disabled = true; try { announce("Loading more members…"); await groupView(groupId, memberPage.next_cursor); } catch (error) { showError(members, error); more.disabled = false; } }; members.append(more); }
      }
     if (isCurrentAdmin(group)) {
          const add = el("form"); add.id = "add-member-form";
          const selectorLegend = el("p", "Start typing a username, then choose a matching account."); selectorLegend.id = "member-selector-help";
          add.append(selectorLegend);
            const memberUsername = formField("Choose a username", "text", "username");
           const usernameInput = memberUsername.querySelector("input");
           usernameInput.id = "add-member-username";
           memberUsername.querySelector("label").htmlFor = usernameInput.id;
           usernameInput.className = "username-filter";
           usernameInput.placeholder = "Type a username to search";
           usernameInput.setAttribute("autocomplete", "off");
          usernameInput.setAttribute("role", "combobox");
          usernameInput.setAttribute("aria-autocomplete", "list");
          usernameInput.setAttribute("aria-controls", "member-username-listbox");
          usernameInput.setAttribute("aria-expanded", "false");
          usernameInput.setAttribute("aria-describedby", "member-selector-help");
          const listbox = el("div");
          listbox.id = "member-username-listbox";
          listbox.setAttribute("role", "listbox");
          listbox.hidden = true;
          listbox.setAttribute("aria-label", "Matching usernames");
          memberUsername.append(listbox);
          add.append(memberUsername);
          let selectedUsername = "";
          let activeIndex = -1;
          let searchGeneration = 0;
          const closeSuggestions = () => {
            listbox.replaceChildren(); listbox.hidden = true;
            usernameInput.setAttribute("aria-expanded", "false");
            usernameInput.removeAttribute("aria-activedescendant"); activeIndex = -1;
          };
           const chooseUsername = username => {
             selectedUsername = String(username);
             usernameInput.value = selectedUsername;
             button.disabled = false;
             closeSuggestions(); usernameInput.focus();
           };
          const showSuggestions = suggestions => {
            listbox.replaceChildren(); activeIndex = -1;
            suggestions.slice(0, 10).forEach((suggestion, index) => {
              const username = typeof suggestion === "string" ? suggestion : suggestion?.username;
              if (!username) return;
              const option = el("div", username); option.id = `member-username-option-${index}`;
              option.setAttribute("role", "option"); option.setAttribute("aria-selected", "false");
              option.onmousedown = event => event.preventDefault();
              option.onclick = () => chooseUsername(username);
              listbox.append(option);
            });
            listbox.hidden = !listbox.children.length;
            usernameInput.setAttribute("aria-expanded", String(!listbox.hidden));
          };
           usernameInput.oninput = async () => {
             selectedUsername = "";
             button.disabled = true;
             const query = usernameInput.value.trim();
            const generation = ++searchGeneration;
            closeSuggestions();
            if (!query) return;
            try {
               const results = itemsOf((await api(`/v1/users/search?username=${encodeURIComponent(query)}`)).data);
              if (generation === searchGeneration) showSuggestions(results);
            } catch (error) { if (generation === searchGeneration) showError(members, error); }
          };
          usernameInput.onkeydown = event => {
            const options = [...listbox.querySelectorAll("[role='option']")];
            if (!options.length) return;
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault(); activeIndex = (activeIndex + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length;
              options.forEach((option, index) => { const active = index === activeIndex; option.setAttribute("aria-selected", String(active)); if (active) usernameInput.setAttribute("aria-activedescendant", option.id); });
            } else if (event.key === "Enter" && activeIndex >= 0) { event.preventDefault(); chooseUsername(options[activeIndex].textContent); }
            else if (event.key === "Escape") closeSuggestions();
          };
           const button = el("button", "Add member"); button.id = "add-member-submit"; button.type = "submit";
           // A typed string is not an identity selection.  Keep the mutation
           // affordance unavailable until the user chooses a server result.
           button.disabled = true;
           add.append(button);
         add.onsubmit = async event => {
         event.preventDefault();
         busy(add, true);
         try {
              const submittedSelector = selectedUsername;
              if (!submittedSelector) {
                showError(members, { message: "Choose a username from the matching suggestions." });
               busy(add, false);
               return;
             }
            const result = await api(`/pool-groups/${id}/members`, {
              method: "POST",
                body: { username: submittedSelector },
              expectedStatus: 201,
            });
            const membership = result.data?.membership || result.data || {};
            announce("Member added.");
             renderMemberImmediately(members, { ...membership, username: submittedSelector });
            // Re-read the members from the server, while carrying the submitted
            // selector into the immediate render when an older response omits it.
             await groupView(groupId, null, { ...membership, username: submittedSelector });
         } catch (error) { showError(members, error); busy(add, false); }
       };
       members.append(add);
     } else {
       // Keep the server-owned authorization boundary intact, but do not make
       // the absence of the control look like a stale/failed render.  This is
       // also useful when a non-admin follows an admin's group URL directly.
       const adminOnly = el("p", "Only this group’s admin can add members.");
       adminOnly.className = "admin-only-notice";
       adminOnly.setAttribute("role", "note");
       members.append(adminOnly);
     }
    section.append(members);
    const pools = card("Pools");
    const poolsList = itemsOf((await api(`/pool-groups/${id}/pools`)).data);
    if (!poolsList.length) pools.append(el("p", "No pools yet."));
      poolsList.forEach(pool => { const row = el("p"); row.append(link(`${pool.question || "Untitled pool"} (${pool.status || "unknown"})`, `#/groups/${pathPart(groupId)}/pools/${pathPart(pool.id)}`)); pools.append(row); });
      if (isCurrentAdmin(group)) {
       const create = el("form");
       create.id = "create-pool-form";
       const questionField = formField("Question", "text", "question");
       const questionInput = questionField.querySelector("input[name='question']");
       questionInput.id = "create-pool-question";
       questionField.querySelector("label").htmlFor = questionInput.id;
       const optionsField = formField("Options (one per line)", "textarea", "options");
        const optionsInput = optionsField.querySelector("textarea[name='options']");
        optionsInput.id = "create-pool-options";
        optionsField.querySelector("label").htmlFor = optionsInput.id;
        create.append(questionField, optionsField);
        const button = el("button", "Create draft");
        button.id = "create-pool-submit";
        button.type = "submit";
        create.append(button);
        create.onsubmit = async event => {
          event.preventDefault();
          // Read from the submitted form rather than relying on a detached
          // control reference. This keeps the binding correct if the view is
          // redrawn before the browser dispatches submit.
          const question = String(create.elements.question.value || "").trim();
          const values = String(create.elements.options.value || "")
            .split("\n").map(value => value.trim()).filter(Boolean);
          if (!question) { showError(pools, { message: "Enter a question." }); return; }
          if (values.length < 2) { showError(pools, { message: "Add at least two options." }); return; }
          busy(create, true);
          try {
            // The API contract requires option objects, not textarea strings.
            // IDs are client-generated option identifiers and are retained by
            // the draft editor for subsequent PATCH requests.
            const options = values.map(label => ({
              id: crypto.randomUUID(),
              label,
            }));
            const result = await api(`/pool-groups/${id}/pools`, {
              method: "POST",
              body: { question, options },
              expectedStatus: 201,
            });
           const pool = result.data;
           if (!pool || typeof pool !== "object" || !pool.id) {
             throw {
               status: result.status,
               code: "INVALID_POOL_RESPONSE",
               message: "The service created the draft but returned no pool ID.",
               requestId: result.requestId,
             };
           }
           // Navigate only from the server-issued id; do not infer it from
           // submitted form values or a stale pool list.
           location.hash = `#/groups/${pathPart(groupId)}/pools/${pathPart(pool.id)}`;
         } catch (error) { showError(pools, error); busy(create, false); }
       };
       pools.append(create);
     }
    section.append(pools);
  } catch (error) { section.replaceChildren(); showError(section, error); }
}

function answerForm(section, groupId, poolId, pool) {
  const form = el("form"); const fieldset = el("fieldset"); fieldset.append(el("legend", "Choose one answer"));
  (pool.options || []).forEach(option => { const label = el("label", option.label); label.className = "option"; const input = el("input"); input.type = "radio"; input.name = "option_id"; input.value = option.id; input.required = true; label.prepend(input); fieldset.append(label); });
  form.append(fieldset); const submit = el("button", pool.has_answered ? "Answer submitted" : "Submit answer"); submit.type = "submit"; submit.disabled = Boolean(pool.has_answered); form.append(submit);
  form.onsubmit = async event => {
    event.preventDefault();
    if (pool.has_answered) return;
    // Capture the selection before busy() disables the controls. FormData
    // omits disabled inputs, which previously sent option_id=null and made
    // the fake-backed E2E flow fail with a 422 before the success live-region
    // announcement could be rendered.
    const optionId = new FormData(form).get("option_id");
    busy(form, true);
    try {
      const result = await api(
        `/pool-groups/${pathPart(groupId)}/pools/${pathPart(poolId)}/answers`,
        { method: "POST", body: { option_id: optionId }, expectedStatus: 201 },
      );
      pool.has_answered = true;
      submit.textContent = "Answer submitted";
      announce(`Answer submitted${result.requestId ? `. Request ID: ${result.requestId}` : "."}`);
    } catch (error) {
      if (error.status === 409) {
        pool.has_answered = true;
        submit.disabled = true;
      }
      showError(section, error);
      if (error.status !== 409) busy(form, false);
    }
  };
  section.append(form);
}

async function resultsView(section, groupId, poolId) {
  try { const results = (await api(`/pool-groups/${pathPart(groupId)}/pools/${pathPart(poolId)}/results`)).data; const box = card("Closed results"); box.append(el("p", `Total answers: ${results.total_answers ?? 0}`)); const list = el("ul"); (results.options || []).forEach(option => list.append(el("li", `${option.label}: ${option.count} (${option.percentage}%)`))); box.append(list); section.append(box); }
  catch (error) { showError(section, error); }
}

async function poolView(groupId, poolId) {
  app.replaceChildren(); const section = card("Pool"); setLoading(section, "Loading pool…"); app.append(section);
  try {
    const pool = (await api(`/pool-groups/${pathPart(groupId)}/pools/${pathPart(poolId)}`)).data;
    const group = (await api(`/pool-groups/${pathPart(groupId)}`)).data;
    section.replaceChildren(el("h2", pool.question || "Pool"), el("p", `Status: ${pool.status || "unknown"}`));
     if (pool.status === "draft" && pool.options) { const form = el("form"); form.append(formField("Question", "text", "question")); form.elements.question.value = pool.question || ""; const options = el("fieldset"); options.append(el("legend", "Answer options")); pool.options.forEach(option => { const field = formField(`Option ${option.id}`, "text", option.id); field.querySelector("input").value = option.label || ""; options.append(field); }); form.append(options); const save = el("button", "Save draft"); save.type = "submit"; form.append(save); form.onsubmit = async event => { event.preventDefault(); busy(form, true); const values = [...options.querySelectorAll("input")].map(input => ({ id: input.name, label: input.value })); if (values.length < 2 || values.some(value => !value.label.trim())) { showError(section, { message: "Add at least two non-empty options." }); busy(form, false); return; } try { const result = await api(`/pool-groups/${pathPart(groupId)}/pools/${pathPart(poolId)}`, { method: "PATCH", body: JSON.stringify({ question: form.elements.question.value, options: values }) }); announce(`Draft saved${result.requestId ? `. Request ID: ${result.requestId}` : "."}`); await poolView(groupId, poolId); } catch (error) { showError(section, error); busy(form, false); } }; section.append(form); }
    if (pool.status === "open") answerForm(section, groupId, poolId, pool);
    if (pool.status === "closed") await resultsView(section, groupId, poolId);
      if (isCurrentAdmin(group) && pool.status !== "closed") {
        const target = pool.status === "draft" ? "open" : "close";
        const action = el("button", target === "open" ? "Open pool" : "Close pool");
        action.type = "button";
        action.onclick = async () => {
          action.disabled = true;
          const idempotencyKey = requestKey();
          try {
            // Lifecycle endpoints return the pool resource directly (not an
            // envelope). Keep one key for this mutation and require the
            // documented success status before rereading the resource.
            const result = await api(
              `/pool-groups/${pathPart(groupId)}/pools/${pathPart(poolId)}/${target}`,
              { method: "POST", idempotencyKey, expectedStatus: 200 },
            );
            if (!result.data || result.data.status !== (target === "open" ? "open" : "closed")) {
              throw {
                status: result.status,
                code: "INVALID_POOL_RESPONSE",
                message: `The service returned an invalid ${target} pool response.`,
                requestId: result.requestId,
              };
            }
            announce(`Pool ${result.data.status}${result.requestId ? `. Request ID: ${result.requestId}` : "."}`);
            // The GET is intentional: it reconciles the visible view with the
            // documented member-safe read model after the mutation.
            await poolView(groupId, poolId);
          } catch (error) { showError(section, error); action.disabled = false; }
        };
        section.append(action);
      }
  } catch (error) { section.replaceChildren(); showError(section, error); }
}

function routeParts() {
  return location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(value => { try { return decodeURIComponent(value); } catch { return ""; } });
}
async function render() {
  const parts = routeParts();
  if (!currentUser) authView();
  else if (!parts.length || (parts[0] === "groups" && parts.length === 1)) await groupsView();
  else if (parts[0] === "groups" && parts.length === 2) await groupView(parts[1]);
  else if (parts[0] === "groups" && parts.length === 4 && parts[2] === "pools") await poolView(parts[1], parts[3]);
  else location.hash = "#/groups";
  focusMain();
}

window.addEventListener("hashchange", render);
(async () => { await loadSession(); await render(); })();
