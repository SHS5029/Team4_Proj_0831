export default function ({ data, setStateValue }) {
  // EventSource는 사용자 header를 지원하지 않으므로 fetch streaming만 사용한다.
  const controller = new AbortController();
  const url = `${data.backend_url}/api/v1/games/${data.game_id}/events`;
  const headers = {"X-User-Id": data.user_id, "X-Request-Id": crypto.randomUUID(), "Last-Event-ID": String(data.last_sequence || 0), "Accept": "text/event-stream"};
  (async () => {
    try {
      const response = await fetch(url, {headers, signal: controller.signal});
      if (!response.ok || !response.body) return;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const item = await reader.read();
        if (item.done) break;
        buffer += decoder.decode(item.value, {stream: true});
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";
        for (const frame of frames) {
          const line = frame.split("\n").find(value => value.startsWith("data:"));
          if (!line) continue;
          try { setStateValue("envelope", JSON.parse(line.slice(5).trim())); } catch (_) { /* 불완전 frame은 폐기 */ }
        }
      }
    } catch (_) { /* Python polling fallback이 복구를 담당한다. */ }
  })();
  return () => controller.abort();
}
