export default function ({ data, setStateValue }) {
  // EventSource는 사용자 header를 지원하지 않으므로 fetch streaming만 사용한다.
  const controller = new AbortController();
  const url = `${data.backend_url}/api/v1/games/${data.game_id}/events`;
  let lastSequence = Number(data.last_sequence || 0);
  let stopped = false;

  // Backend의 SSE 응답은 현재 batch와 heartbeat를 보낸 뒤 연결을 닫을 수 있다.
  // 연결 종료를 곧바로 오류로 확정하지 않고, 마지막으로 적용한 sequence부터
  // 재연결해야 PASS 직후의 phase 전환을 놓쳐도 다음 연결에서 복구할 수 있다.
  const wait = (milliseconds) => new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    controller.signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    }, {once: true});
  });

  (async () => {
    while (!stopped) {
      try {
        const headers = {
          "X-User-Id": data.user_id,
          "X-Request-Id": crypto.randomUUID(),
          "Last-Event-ID": String(lastSequence),
          "Accept": "text/event-stream",
        };
        const response = await fetch(url, {headers, signal: controller.signal});
        if (!response.ok || !response.body) {
          throw new Error(`SSE_HTTP_${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!stopped) {
          const item = await reader.read();
          if (item.done) break;
          buffer += decoder.decode(item.value, {stream: true});
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() || "";
          for (const frame of frames) {
            const line = frame.split(/\r?\n/).find(value => value.startsWith("data:"));
            if (!line) continue;
            try {
              const envelope = JSON.parse(line.slice(5).trim());
              const dataPart = envelope?.data || envelope;
              const receivedSequence = dataPart?.last_sequence;
              const hasOperations = Array.isArray(dataPart?.operations)
                && dataPart.operations.length > 0;
              const isSnapshot = dataPart?.mode === "SNAPSHOT"
                && dataPart?.snapshot;
              const hasCursorAdvance = Number.isInteger(receivedSequence)
                && receivedSequence > lastSequence;
              if (Number.isInteger(receivedSequence)) {
                lastSequence = Math.max(lastSequence, receivedSequence);
              }
              // 현재 cursor를 그대로 돌려주는 no-op DELTA는 heartbeat 성격의
              // 응답이다. 이를 state로 기록하면 1초 재연결마다 Streamlit 전체가
              // rerun되어 사용자가 페이지를 조작할 수 없게 되므로 폐기한다.
              if (hasOperations || hasCursorAdvance || isSnapshot) {
                setStateValue("envelope", envelope);
              }
            } catch (_) { /* 불완전 frame은 다음 frame에서 다시 처리하지 않고 폐기한다. */ }
          }
        }
        if (!stopped) {
          await wait(1000);
        }
      } catch (_) {
        if (!stopped) {
          await wait(1000);
        }
      }
    }
  })();
  return () => { stopped = true; controller.abort(); };
}
