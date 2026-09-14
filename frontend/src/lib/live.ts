/**
 * Live updates: one socket per browser tab, shared by every screen.
 *
 * **A doorbell.** The server says only "the queue at this facility changed";
 * the screen that hears it refetches through the ordinary API, where
 * authorisation already lives. Nothing sensitive crosses this socket.
 *
 * **Polling stays as the safety net.** A socket can drop, a proxy can buffer,
 * Redis can restart. The screens keep their intervals — the doorbell makes
 * them immediate when it works, and they are merely as they were when it
 * does not.
 *
 * **Authenticated by message.** The token is sent as the first frame rather
 * than in the URL, because a URL is written into every access log it passes.
 */

import { organizationStore, tokenStore } from "@/lib/api";

type Listener = () => void;

const listeners = new Map<string, Set<Listener>>();
let socket: WebSocket | null = null;
let ready = false;
let retry = 0;
let reconnectTimer: number | undefined;
const pending = new Map<string, number>();

/** One save can ring several times (an observation and the alert it raised);
 * a quarter of a second folds those into a single refetch. */
const COALESCE_MS = 250;

function url(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/`;
}

function send(message: unknown) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function connect() {
  const token = tokenStore.get();
  const organization = organizationStore.get();
  // Signed out, or a platform user with no hospital: nothing to listen to.
  if (!token || !organization || socket) return;

  try {
    socket = new WebSocket(url());
  } catch {
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    send({ type: "auth", token, organization });
  };

  socket.onmessage = (event) => {
    let message: { type?: string; topic?: string };
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.type === "ready") {
      ready = true;
      retry = 0;
      // Topics chosen before the socket was ready, or before a reconnect.
      for (const topic of listeners.keys()) {
        if (topic !== "notifications") send({ type: "subscribe", topic });
      }
      return;
    }
    if (message.type === "changed" && message.topic) {
      const topic = message.topic;
      if (pending.has(topic)) return;
      pending.set(
        topic,
        window.setTimeout(() => {
          pending.delete(topic);
          listeners.get(topic)?.forEach((listener) => listener());
        }, COALESCE_MS),
      );
    }
  };

  socket.onclose = () => {
    socket = null;
    ready = false;
    if (listeners.size > 0) scheduleReconnect();
  };
}

function scheduleReconnect() {
  window.clearTimeout(reconnectTimer);
  // 1s, 2s, 4s … capped at 30s: a server restart is not met with a stampede
  // from every board in the building at once.
  const delay = Math.min(30_000, 1000 * 2 ** retry);
  retry += 1;
  reconnectTimer = window.setTimeout(connect, delay);
}

/**
 * Hear when `topic` changes. Returns the function that stops listening.
 * Topics: `"notifications"`; `"queue.<facility>"`, `"beds.<facility>"`,
 * `"ed.<facility>"`, `"lab.<facility>"` by facility uuid; `"icu.<ward uuid>"`.
 */
export function listen(topic: string, onChange: Listener): () => void {
  let set = listeners.get(topic);
  if (!set) {
    set = new Set();
    listeners.set(topic, set);
    if (ready && topic !== "notifications") send({ type: "subscribe", topic });
  }
  set.add(onChange);
  connect();

  return () => {
    const current = listeners.get(topic);
    current?.delete(onChange);
    if (current && current.size === 0) listeners.delete(topic);
    // The last screen gone: close rather than hold a connection for nobody.
    if (listeners.size === 0 && socket) {
      socket.close();
      socket = null;
    }
  };
}
