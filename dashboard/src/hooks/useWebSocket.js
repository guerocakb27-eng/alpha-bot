import { useEffect, useRef, useState } from "react";

export function useWebSocket(path = "/ws/live") {
  const [status, setStatus] = useState("connecting"); // connecting | open | closed
  const [lastEvent, setLastEvent] = useState(null);
  const [events, setEvents] = useState([]);
  const wsRef = useRef(null);
  const reconnectMs = useRef(1000);
  const pingId = useRef(null);

  useEffect(() => {
    let killed = false;

    function connect() {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}${path}`);
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        setStatus("open");
        reconnectMs.current = 1000;
        pingId.current = setInterval(() => {
          try { ws.send("ping"); } catch { /* drop */ }
        }, 20000);
      };

      ws.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data);
          setLastEvent(payload);
          setEvents((prev) => [payload, ...prev].slice(0, 100));
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        setStatus("closed");
        clearInterval(pingId.current);
        if (killed) return;
        const next = Math.min(reconnectMs.current * 2, 15000);
        reconnectMs.current = next;
        setTimeout(connect, next);
      };

      ws.onerror = () => { try { ws.close(); } catch { /* drop */ } };
    }

    connect();
    return () => {
      killed = true;
      clearInterval(pingId.current);
      try { wsRef.current?.close(); } catch { /* drop */ }
    };
  }, [path]);

  return { status, lastEvent, events };
}
