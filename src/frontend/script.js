const chatWindow = document.getElementById("chatWindow");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const modeBadge = document.getElementById("modeBadge");

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

async function sendMessage(message) {
    const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
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
    messageInput.value = "";
    sendBtn.disabled = true;

    try {
        await sendMessage(message);
    } catch (error) {
        appendMessage("assistant", `Network error: ${error.message}`, "error");
    } finally {
        sendBtn.disabled = false;
        messageInput.focus();
    }
});

detectMode();
