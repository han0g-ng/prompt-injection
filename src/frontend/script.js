const chatWindow = document.getElementById("chatWindow");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const modeBadge = document.getElementById("modeBadge");
const activeModelBadge = document.getElementById("activeModelBadge");
const modelSelect = document.getElementById("modelSelect");
const modelHint = document.getElementById("modelHint");
const MODEL_STORAGE_KEY = "prompt_demo_selected_model";
const MODEL_FETCH_TIMEOUT_MS = 4000;
const FALLBACK_MODELS = [
    "phi3:mini",
    "qwen2.5-coder:1.5b",
    "deepseek-coder:1.3b",
    "gemma2:2b",
    "tinyllama:1.1b",
    "dolphin-phi:2.7b",
];

function detectMode() {
    const port = window.location.port;
    if (port === "8001") {
        modeBadge.textContent = "Secure Mode";
    } else {
        modeBadge.textContent = "Vulnerable Mode";
    }
}

function appendMessage(role, text, extraClass = "") {
    const article = document.createElement("article");
    article.className = `message ${role} ${extraClass}`.trim();

    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = role;

    const body = document.createElement("p");
    body.textContent = text;

    article.appendChild(meta);
    article.appendChild(body);
    chatWindow.appendChild(article);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function autoResizeInput() {
    messageInput.style.height = "auto";
    const nextHeight = Math.min(messageInput.scrollHeight, 170);
    messageInput.style.height = `${nextHeight}px`;
}

function setModelHint(text, isError = false) {
    modelHint.textContent = text;
    modelHint.classList.toggle("error", isError);
}

function setActiveModelBadge(modelName) {
    activeModelBadge.textContent = `Model: ${modelName}`;
}

function renderModelOptions(models, preferred = "") {
    modelSelect.innerHTML = "";
    for (const modelName of models) {
        const option = document.createElement("option");
        option.value = modelName;
        option.textContent = modelName;
        modelSelect.appendChild(option);
    }

    const saved = localStorage.getItem(MODEL_STORAGE_KEY);
    const selected = models.includes(saved)
        ? saved
        : (models.includes(preferred) ? preferred : models[0]);

    modelSelect.value = selected;
    setActiveModelBadge(selected);
    setModelHint(`Using 1 active model: ${selected}`);
}

async function loadModels() {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), MODEL_FETCH_TIMEOUT_MS);

    try {
        const response = await fetch("/api/models", { signal: controller.signal });
        if (!response.ok) {
            throw new Error(`Unable to load model list (${response.status})`);
        }

        const payload = await response.json();
        const allowedModels = Array.isArray(payload.allowed_models) ? payload.allowed_models : [];
        const defaultModel = payload.default_model || "";

        if (!allowedModels.length) {
            throw new Error("No allowed model returned by backend");
        }

        renderModelOptions(allowedModels, defaultModel);
    } catch (error) {
        renderModelOptions(FALLBACK_MODELS, "phi3:mini");
        const reason = error?.name === "AbortError"
            ? `timeout after ${MODEL_FETCH_TIMEOUT_MS}ms`
            : error.message;
        setModelHint(`Model list unavailable. Using fallback list (${reason})`, true);
    } finally {
        clearTimeout(timeoutId);
    }
}

modelSelect.addEventListener("change", () => {
    const selected = modelSelect.value;
    localStorage.setItem(MODEL_STORAGE_KEY, selected);
    setModelHint(`Using 1 active model: ${selected}`);
    setActiveModelBadge(selected);
});

async function sendMessage(message, model) {
    const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, model }),
    });

    if (!response.ok) {
        const errorPayload = await response.json().catch(() => ({}));
        const detail = errorPayload.detail || `Request failed with status ${response.status}`;
        appendMessage("assistant", detail, "error");
        return;
    }

    const data = await response.json();
    appendMessage("assistant", data.response || "No response from model.");
}

chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const message = messageInput.value.trim();
    if (!message) {
        return;
    }

    appendMessage("user", message);
    const selectedModel = modelSelect.value;
    messageInput.value = "";
    autoResizeInput();
    sendBtn.disabled = true;
    modelSelect.disabled = true;

    try {
        await sendMessage(message, selectedModel);
    } catch (error) {
        appendMessage("assistant", `Network error: ${error.message}`, "error");
    } finally {
        sendBtn.disabled = false;
        modelSelect.disabled = false;
        messageInput.focus();
    }
});

messageInput.addEventListener("input", autoResizeInput);

messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        chatForm.requestSubmit();
    }
});

detectMode();
loadModels();
autoResizeInput();
