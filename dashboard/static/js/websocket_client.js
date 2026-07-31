class WebSocketClient {
    constructor() {
        this.listeners = [];
        this.connected = false;
        this.connect();
    }

    connect() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/evolution`);

        this.ws.onopen = () => {
            this.connected = true;
            console.log("WebSocket connected");
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.notify(data);
            } catch (e) {
                console.error("Error parsing WebSocket message:", e);
            }
        };

        this.ws.onclose = () => {
            this.connected = false;
            console.log("WebSocket disconnected, reconnecting in 5s...");
            setTimeout(() => this.connect(), 5000);
        };

        this.ws.onerror = (err) => {
            console.error("WebSocket error:", err);
            this.ws.close();
        };
    }

    addListener(callback) {
        this.listeners.push(callback);
    }

    removeListener(callback) {
        this.listeners = this.listeners.filter(cb => cb !== callback);
    }

    notify(data) {
        this.listeners.forEach(cb => {
            try {
                cb(data);
            } catch (e) {
                console.error("Error invoking listener callback:", e);
            }
        });
    }
}

export const wsClient = new WebSocketClient();
