const instances = new WeakMap();

export default function ({ data, parentElement }) {
  // 같은 행동 window의 매초 countdown rerender에는 focus를 다시 빼앗거나 같은
  // 문구를 반복해서 읽지 않는다. 임계 경고가 바뀔 때만 live region을 갱신한다.
  const previous = instances.get(parentElement) || {
    windowId: null,
    pendingWindowId: null,
    announcement: null,
  };
  const windowId = typeof data?.window_id === "string" ? data.window_id : null;
  const announcement = typeof data?.announcement === "string" ? data.announcement : null;
  if (announcement !== previous.announcement) {
    const liveRegion = parentElement.querySelector("[data-ai-mafia-action-attention]");
    if (liveRegion) liveRegion.textContent = announcement || "";
    previous.announcement = announcement;
  }
  if (
    !data?.active
    || windowId === null
    || previous.windowId === windowId
    || previous.pendingWindowId === windowId
  ) {
    instances.set(parentElement, previous);
    return;
  }
  previous.pendingWindowId = windowId;
  instances.set(parentElement, previous);

  const focusWhenReady = attemptsRemaining => requestAnimationFrame(() => {
    const documentRoot = parentElement.ownerDocument;
    const region = documentRoot.querySelector('[class*="st-key-current-action-region"]');
    const preferredInput = region?.querySelector(
      'textarea:not([disabled]), input[type="radio"]:not([disabled])'
    );
    if ((!region || !preferredInput) && attemptsRemaining > 0) {
      setTimeout(() => focusWhenReady(attemptsRemaining - 1), 50);
      return;
    }
    previous.pendingWindowId = null;
    if (!region) return;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    region.scrollIntoView({block: "start", behavior: reducedMotion ? "auto" : "smooth"});
    const focusTarget = preferredInput || region.querySelector("button:not([disabled])") || region;
    if (focusTarget === region) region.setAttribute("tabindex", "-1");
    focusTarget.focus({preventScroll: true});
    previous.windowId = windowId;
  });
  focusWhenReady(5);
}
