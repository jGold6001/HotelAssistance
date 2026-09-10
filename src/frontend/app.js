/**
 * Chat client for the Hotel Assistance API.
 *
 * Reads the NDJSON stream from POST /api/chat/stream so the thinking
 * indicator shows the stage the backend is actually in, not a fake timer.
 */

const SESSION_ID = "web";

const STAGE_LABELS = {
  retrieving_candidates: "Looking through the filter catalog…",
  extracting_intent: "Reading your request…",
  validating: "Validating the filter changes…",
  searching_offers: "Checking the hotel backend…",
  done: "Wrapping up…",
};

const WELCOME =
  "Tell me about the stay you are looking for — destination, dates, who is travelling, " +
  "and anything the hotel or room needs to have. I will turn it into search filters and " +
  "tell you what I could not map.";

const elements = {
  messages: document.getElementById("messages"),
  form: document.getElementById("composer"),
  input: document.getElementById("message-input"),
  sendButton: document.getElementById("send-button"),
  resetButton: document.getElementById("reset-button"),
  suggestions: document.getElementById("suggestions"),
  backendStatus: document.getElementById("backend-status"),
  destination: document.getElementById("state-destination"),
  dates: document.getElementById("state-dates"),
  guests: document.getElementById("state-guests"),
  filters: document.getElementById("state-filters"),
  filterCount: document.getElementById("filter-count"),
  offersBox: document.getElementById("offers-box"),
  offersCount: document.getElementById("offers-count"),
};

let busy = false;

/* ---------------------------------------------------------------- rendering */

function addMessage(role, text) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  wrapper.appendChild(bubble);
  elements.messages.appendChild(wrapper);
  scrollToBottom();
  return bubble;
}

function addNotes(bubble, notes) {
  if (!notes.length) return;
  const list = document.createElement("div");
  list.className = "bubble-notes";
  for (const note of notes) {
    const line = document.createElement("span");
    line.textContent = note;
    list.appendChild(line);
  }
  bubble.appendChild(list);
  scrollToBottom();
}

/**
 * The properties behind the offer count, as a table under the reply.
 *
 * Everything here is backend data passed straight through - the client
 * neither sorts, filters nor invents a row.
 */
function addOffersTable(offers, total) {
  if (!offers || !offers.length) return;

  const wrapper = document.createElement("div");
  wrapper.className = "message assistant";

  const panel = document.createElement("div");
  panel.className = "offers-panel";

  const title = document.createElement("div");
  title.className = "offers-panel-title";
  const found = total === null || total === undefined ? offers.length : total;
  title.textContent = `${found} propert${found === 1 ? "y" : "ies"} found`;
  if (offers.length < found) {
    const shown = document.createElement("span");
    shown.className = "offers-panel-note";
    shown.textContent = `showing ${offers.length}`;
    title.appendChild(shown);
  }

  const scroll = document.createElement("div");
  scroll.className = "offers-scroll";

  const table = document.createElement("table");
  table.className = "offers-table";
  table.appendChild(buildTableHead(["#", "Apartment", "Address", "Price"]));

  const body = document.createElement("tbody");
  offers.forEach((offer, index) => {
    const row = document.createElement("tr");
    row.append(
      buildCell(String(index + 1), "offers-index"),
      buildCell(offer.apartment),
      buildCell(offer.address, "offers-address"),
      buildCell(offer.price, "offers-price"),
    );
    body.appendChild(row);
  });
  table.appendChild(body);

  scroll.appendChild(table);
  panel.append(title, scroll);
  wrapper.appendChild(panel);
  elements.messages.appendChild(wrapper);
  scrollToBottom();
}

function buildTableHead(labels) {
  const head = document.createElement("thead");
  const row = document.createElement("tr");
  for (const label of labels) {
    const cell = document.createElement("th");
    cell.textContent = label;
    row.appendChild(cell);
  }
  head.appendChild(row);
  return head;
}

function buildCell(text, className) {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (className) cell.className = className;
  return cell;
}

function showThinking() {
  const wrapper = document.createElement("div");
  wrapper.className = "message assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble thinking";

  const dots = document.createElement("span");
  dots.className = "dots";
  dots.innerHTML = "<span></span><span></span><span></span>";

  const stage = document.createElement("span");
  stage.className = "thinking-stage";
  stage.textContent = "Thinking…";

  const elapsed = document.createElement("span");
  elapsed.className = "thinking-elapsed";
  elapsed.textContent = "0.0s";

  bubble.append(dots, stage, elapsed);
  wrapper.appendChild(bubble);
  elements.messages.appendChild(wrapper);
  scrollToBottom();

  const startedAt = performance.now();
  const timer = window.setInterval(() => {
    elapsed.textContent = `${((performance.now() - startedAt) / 1000).toFixed(1)}s`;
  }, 100);

  return {
    setStage(name) {
      stage.textContent = STAGE_LABELS[name] || "Thinking…";
    },
    remove() {
      window.clearInterval(timer);
      wrapper.remove();
    },
  };
}

function scrollToBottom() {
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function setBusy(value) {
  busy = value;
  elements.sendButton.disabled = value;
  elements.input.disabled = value;
  if (!value) elements.input.focus();
}

/* ------------------------------------------------------------- state panel */

function renderState(state) {
  setFact(elements.destination, state.destination);
  setFact(elements.dates, formatDates(state.check_in, state.check_out));
  setFact(elements.guests, formatGuests(state.adults, state.children));
  markPending(state.pending);

  elements.filterCount.textContent = String(state.filters.length);
  elements.filters.replaceChildren();

  if (!state.filters.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No filters yet.";
    elements.filters.appendChild(empty);
    return;
  }

  for (const filter of state.filters) {
    const item = document.createElement("li");
    item.title = filter.filter_id;

    const label = document.createElement("span");
    label.textContent = filter.label;

    const meta = document.createElement("span");
    meta.className = "filter-value";
    meta.textContent = filter.value_label;
    if (filter.strength === "preferred") {
      const strength = document.createElement("span");
      strength.className = "filter-strength";
      strength.textContent = " preferred";
      meta.appendChild(strength);
    }

    item.append(label, meta);
    elements.filters.appendChild(item);
  }
}

function setFact(node, value) {
  node.textContent = value || "not set";
  node.classList.toggle("empty", !value);
}

/**
 * Say why a trip detail went blank: the user replaced it without pinning it
 * down, so it is waiting on an answer rather than never having been set.
 */
function markPending(pending) {
  const fields = {
    destination: elements.destination,
    dates: elements.dates,
    guests: elements.guests,
  };
  for (const node of Object.values(fields)) node.classList.remove("pending");

  const node = pending && fields[pending.field];
  if (!node) return;
  node.textContent = `waiting \u2014 you said \u201c${pending.hint}\u201d`;
  node.classList.remove("empty");
  node.classList.add("pending");
}

function formatDates(checkIn, checkOut) {
  if (!checkIn && !checkOut) return "";
  if (checkIn && checkOut) return `${checkIn} → ${checkOut}`;
  return checkIn ? `from ${checkIn}` : `until ${checkOut}`;
}

function formatGuests(adults, children) {
  if (adults === null || adults === undefined) return "";
  const parts = [`${adults} adult${adults === 1 ? "" : "s"}`];
  if (children) parts.push(`${children} child${children === 1 ? "" : "ren"}`);
  return parts.join(", ");
}

function renderOffers(payload) {
  if (!payload.backend_available || payload.available_offers_count === null) {
    elements.offersBox.hidden = true;
    return;
  }
  elements.offersBox.hidden = false;
  elements.offersCount.textContent = String(payload.available_offers_count);
}

/** Extra context worth showing under the reply, but not worth burying it in. */
function collectNotes(payload) {
  const notes = [];
  for (const item of payload.unmapped_requests) notes.push(`Not supported: ${item}`);
  for (const issue of payload.issues) {
    if (issue.code !== "not_applied") notes.push(issue.message);
  }
  for (const suggestion of payload.relaxation_suggestions) {
    notes.push(`Relax: ${suggestion.label}`);
  }
  return notes;
}

/* ------------------------------------------------------------------ network */

async function sendMessage(message) {
  if (busy || !message.trim()) return;

  addMessage("user", message);
  elements.suggestions.hidden = true;
  setBusy(true);
  const thinking = showThinking();

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: SESSION_ID }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`Request failed with status ${response.status}`);
    }

    await readStream(response.body, thinking);
  } catch (error) {
    thinking.remove();
    addMessage("error", `Could not reach the assistant: ${error.message}`);
  } finally {
    thinking.remove();
    setBusy(false);
  }
}

async function readStream(body, thinking) {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += value;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.trim()) handleEvent(JSON.parse(line), thinking);
    }
  }

  if (buffer.trim()) handleEvent(JSON.parse(buffer), thinking);
}

function handleEvent(event, thinking) {
  if (event.type === "stage") {
    thinking.setStage(event.stage);
    return;
  }

  thinking.remove();

  if (event.type === "error") {
    addMessage("error", event.message);
    return;
  }

  const bubble = addMessage("assistant", event.reply);
  addNotes(bubble, collectNotes(event));
  addOffersTable(event.offers, event.available_offers_count);
  renderState(event.state);
  renderOffers(event);
}

async function resetSearch() {
  if (busy) return;
  setBusy(true);
  try {
    const response = await fetch(`/api/state/reset?session_id=${encodeURIComponent(SESSION_ID)}`, {
      method: "POST",
    });
    renderState(await response.json());
    elements.messages.replaceChildren();
    elements.offersBox.hidden = true;
    elements.suggestions.hidden = false;
    addMessage("assistant", WELCOME);
  } catch (error) {
    addMessage("error", `Could not reset the search: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function loadInitialState() {
  try {
    const [health, state] = await Promise.all([
      fetch("/health").then((response) => response.json()),
      fetch(`/api/state?session_id=${encodeURIComponent(SESSION_ID)}`).then((response) => response.json()),
    ]);

    renderState(state);
    if (health.llm_configured) {
      elements.backendStatus.textContent = `${health.filters} filters · ${health.retrieval_mode} retrieval`;
      elements.backendStatus.className = "pill pill-ok";
    } else {
      elements.backendStatus.textContent = "OpenAI API key not configured";
      elements.backendStatus.className = "pill pill-warn";
    }
  } catch {
    elements.backendStatus.textContent = "backend unreachable";
    elements.backendStatus.className = "pill pill-warn";
  }
}

/* -------------------------------------------------------------------- setup */

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = elements.input.value.trim();
  elements.input.value = "";
  autoGrow();
  sendMessage(message);
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});

elements.input.addEventListener("input", autoGrow);

function autoGrow() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 160)}px`;
}

elements.suggestions.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button) sendMessage(button.textContent.trim());
});

elements.resetButton.addEventListener("click", resetSearch);

addMessage("assistant", WELCOME);
loadInitialState();
elements.input.focus();
