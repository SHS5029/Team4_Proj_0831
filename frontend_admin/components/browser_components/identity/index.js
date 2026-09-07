export default function ({ data, setStateValue }) {
  // 관리자 UUID도 강한 인증이 아니므로 Backend allowlist 검사를 반드시 통과해야 한다.
  const key = data?.storage_key || "ai_mafia_admin_user_id_v1";
  const valid = value => typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  let userId = null;
  try {
    userId = window.localStorage.getItem(key);
    if (!valid(userId)) userId = crypto.randomUUID();
    window.localStorage.setItem(key, userId);
  } catch (_) { userId = null; }
  setStateValue("user_id", valid(userId) ? userId : null);
}
