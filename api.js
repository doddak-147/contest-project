const Api = {
  enabled: false,
  user: null,
  csrf: "",
  async request(path, options = {}) {
    const headers = { Accept: "application/json", ...options.headers };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (this.csrf && options.method && options.method !== "GET") headers["X-CSRF-Token"] = this.csrf;
    const response = await fetch(path, { ...options, headers, credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : "입력값을 확인한 뒤 다시 시도하세요.");
      error.status = response.status;
      throw error;
    }
    return data;
  },
  async initialize() {
    const response = await fetch("/api/health");
    if (response.status === 404) return;
    const health = await response.json().catch(() => null);
    if (!health || health.status !== "ok") throw new Error("서버 연결을 확인해 주세요.");
    this.enabled = true;
    try {
      this.setSession(await this.request("/api/auth/me"));
    } catch (error) {
      if (error.status !== 401) throw error;
      this.setSession(null);
    }
  },
  setSession(session) {
    this.user = session?.user || null;
    this.csrf = session?.csrf_token || "";
    document.getElementById("accountButton").hidden = !this.enabled || Boolean(this.user);
    document.getElementById("logoutButton").hidden = !this.user;
    document.getElementById("accountName").textContent = this.user?.display_name || "";
    document.getElementById("adminLink").hidden = this.user?.role !== "admin";
    document.getElementById("storageNote").textContent = this.user
      ? "계정에 저장한 도전 기록은 다른 기기에서도 이어볼 수 있어요."
      : "지금은 이 브라우저에 저장돼요. 로그인하면 계정으로 관리할 수 있어요.";
  },
};

let accountMode = "login";
const accountDialog = document.getElementById("accountDialog");
const accountForm = document.getElementById("accountForm");

document.getElementById("accountButton").addEventListener("click", () => accountDialog.showModal());
document.getElementById("closeAccount").addEventListener("click", () => accountDialog.close());
document.getElementById("accountSwitch").addEventListener("click", () => {
  accountMode = accountMode === "login" ? "register" : "login";
  const register = accountMode === "register";
  document.getElementById("accountTitle").textContent = register ? "새 계정 만들기" : "도전을 이어가세요";
  document.getElementById("displayNameField").hidden = !register;
  document.getElementById("displayName").required = register;
  document.getElementById("accountSubmit").textContent = register ? "가입하고 시작하기" : "로그인";
  document.getElementById("accountSwitch").textContent = register ? "이미 계정이 있어요" : "처음이신가요? 계정 만들기";
  document.getElementById("password").autocomplete = register ? "new-password" : "current-password";
  document.getElementById("accountError").textContent = "";
});
accountForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("accountSubmit");
  button.disabled = true;
  document.getElementById("accountError").textContent = "";
  try {
    const body = { username: document.getElementById("username").value.trim(), password: document.getElementById("password").value };
    if (accountMode === "register") body.display_name = document.getElementById("displayName").value.trim();
    Api.setSession(await Api.request(`/api/auth/${accountMode}`, { method: "POST", body }));
    accountForm.reset();
    accountDialog.close();
    document.dispatchEvent(new CustomEvent("contestly:session"));
  } catch (error) {
    document.getElementById("accountError").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
document.getElementById("logoutButton").addEventListener("click", async () => {
  try {
    await Api.request("/api/auth/logout", { method: "POST" });
    Api.setSession(null);
    document.dispatchEvent(new CustomEvent("contestly:session"));
  } catch (error) {
    document.getElementById("toast").textContent = error.message;
    document.getElementById("toast").classList.add("show");
  }
});
