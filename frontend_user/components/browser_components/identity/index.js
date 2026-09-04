export default function ({ data, setStateValue }) {
  // 저장값은 UUID v4 형식으로만 사용하고 임의의 값은 Python으로 반환하지 않는다.
  const key = data?.storage_key || "ai_mafia_user_id_v1";
  const valid = value => typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  let persistence = "LOCAL";
  let userId = null;
  try {
    userId = window.localStorage.getItem(key);
    if (!valid(userId)) userId = crypto.randomUUID();
    window.localStorage.setItem(key, userId);
  } catch (_) {
    persistence = "SESSION_ONLY";
    userId = valid(userId) ? userId : crypto.randomUUID();
  }
  setStateValue("identity", {
    schema_version: 1,
    component_instance_id: data?.component_instance_id,
    scope_version: data?.scope_version,
    user_id: userId,
    persistence,
  });
}
