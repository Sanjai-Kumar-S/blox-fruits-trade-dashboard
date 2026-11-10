document.addEventListener("DOMContentLoaded", () => {
    const terminalWindow = document.getElementById("terminalWindow");
    const queueCountBadge = document.getElementById("queueCountBadge");
    const pollCountBadge = document.getElementById("pollCountBadge");
    const nextPayloadPreview = document.getElementById("nextPayloadPreview");
    const lastPollTime = document.getElementById("lastPollTime");
    const statusDot = document.getElementById("statusDot");
    const statusText = document.getElementById("statusText");
    const customCommandForm = document.getElementById("customCommandForm");
    const itemInput = document.getElementById("itemInput");
    const normalizeToggle = document.getElementById("normalizeToggle");
    const showEmptyPollsToggle = document.getElementById("showEmptyPollsToggle");
    const simulatePollBtn = document.getElementById("simulatePollBtn");
    const clearQueueBtn = document.getElementById("clearQueueBtn");
    const clearTerminalBtn = document.getElementById("clearTerminalBtn");

    let renderedLogIds = new Set();
    let cachedLogs = [];

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function renderTerminalLogs(logs, forceRebuild = false) {
        const showEmpty = showEmptyPollsToggle.checked;

        if (forceRebuild) {
            terminalWindow.innerHTML = "";
            renderedLogIds.clear();
        }

        let appended = false;
        for (const entry of logs) {
            if (!showEmpty && entry.type === "POLL_EMPTY") {
                continue;
            }
            if (renderedLogIds.has(entry.id)) {
                continue;
            }
            renderedLogIds.add(entry.id);

            const line = document.createElement("div");
            line.className = `log-line log-${entry.type}`;

            const payloadHtml = entry.payload
                ? `<span class="log-payload">&rarr; JSON: <code>${escapeHtml(JSON.stringify(entry.payload))}</code></span>`
                : "";

            line.innerHTML = `
                <span class="log-time">[${escapeHtml(entry.timestamp)}]</span>
                <span class="log-badge">${escapeHtml(entry.type)}</span>
                <div class="log-msg">
                    ${escapeHtml(entry.message)}
                    ${payloadHtml}
                </div>
            `;
            terminalWindow.appendChild(line);
            appended = true;
        }

        if (appended) {
            terminalWindow.scrollTop = terminalWindow.scrollHeight;
        }
    }

    async function sendCommand(commandStr, normalize = true, source = "Dashboard UI") {
        try {
            const response = await fetch("/api/command", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    command: commandStr,
                    normalize: normalize,
                    source: source
                })
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || "Failed to queue command");
            }
            await syncStatus();
        } catch (err) {
            console.error("Command dispatch error:", err);
        }
    }

    async function syncStatus() {
        try {
            const res = await fetch("/api/status");
            if (!res.ok) throw new Error("Status fetch failed");
            const data = await res.json();

            // Update badges
            const queue = data.queue || [];
            queueCountBadge.textContent = queue.length;
            pollCountBadge.textContent = data.stats?.total_polled ?? 0;

            const nextCmd = queue.length > 0 ? queue[0] : null;
            nextPayloadPreview.textContent = JSON.stringify({ command: nextCmd });

            if (data.stats?.last_poll_at) {
                const dt = new Date(data.stats.last_poll_at);
                lastPollTime.textContent = `Last poll: ${dt.toLocaleTimeString()}`;
            }

            statusDot.style.background = "#10b981";
            statusText.textContent = "Backend Online";

            cachedLogs = data.logs || [];
            renderTerminalLogs(cachedLogs, false);
        } catch (err) {
            statusDot.style.background = "#f43f5e";
            statusText.textContent = "Backend Offline";
        }
    }

    // Bind Quick Action Buttons
    document.querySelectorAll(".action-buttons-grid .btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const cmd = btn.getAttribute("data-command");
            const label = btn.getAttribute("data-label");
            sendCommand(cmd, false, `Action: ${label}`);
        });
    });

    // Bind Custom Item Input Form
    customCommandForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const rawVal = itemInput.value.trim();
        if (!rawVal) return;
        sendCommand(rawVal, normalizeToggle.checked, "Item Dispatcher");
        itemInput.value = "";
        itemInput.focus();
    });

    // Bind Quick Preset Chips
    document.querySelectorAll(".chip").forEach((chip) => {
        chip.addEventListener("click", () => {
            const preset = chip.getAttribute("data-preset");
            itemInput.value = preset;
            itemInput.focus();
        });
    });

    // Simulate Roblox Client Poll (GET /get_commands)
    simulatePollBtn.addEventListener("click", async () => {
        try {
            await fetch("/get_commands");
            await syncStatus();
        } catch (err) {
            console.error("Failed to simulate poll:", err);
        }
    });

    // Clear Pending Queue
    clearQueueBtn.addEventListener("click", async () => {
        await fetch("/api/queue/clear", { method: "POST" });
        await syncStatus();
    });

    // Clear Terminal Logs
    clearTerminalBtn.addEventListener("click", async () => {
        await fetch("/api/logs/clear", { method: "POST" });
        renderedLogIds.clear();
        terminalWindow.innerHTML = "";
        await syncStatus();
    });

    // Toggle Empty Polls Filter
    showEmptyPollsToggle.addEventListener("change", () => {
        renderTerminalLogs(cachedLogs, true);
    });

    // Initial sync + polling interval
    syncStatus();
    setInterval(syncStatus, 1200);
});
