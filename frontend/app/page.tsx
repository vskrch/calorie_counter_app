"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
 import {
  AdminOverview,
  AdminUser,
  ImageAnalysisResult,
  MealEntry,
  ProviderSessionStatus,
  SummaryResponse,
  UserSummary,
  adminConnectPerplexityWeb,
  adminDeleteUser,
  adminDisconnectPerplexityWeb,
  adminOverview,
  adminPerplexityWebStatus,
  adminResetCode,
  adminUsers,
  analyzeManual,
  analyzePhoto,
  createSession,
  deleteMeal,
  getMeals,
  getSummary,
  register,
} from "./lib/api";

type AppMode = "auth" | "user" | "admin";

type Notice = {
  type: "error" | "success" | "info";
  text: string;
};

const STORAGE_KEY = "cc_access_code";
const PERPLEXITY_KEY_STORAGE = "cc_perplexity_api_key";
const OPENROUTER_KEY_STORAGE = "cc_openrouter_api_key";

const MANUAL_PROMPT = `Analyze this food image and return strict JSON only with keys:
- dish
- calories_kcal
- protein_g
- fiber_g
- nutrients (array)
- chemicals (array)
- notes`;

export default function Home() {
  const [mode, setMode] = useState<AppMode>("auth");
  const [name, setName] = useState("");
  const [codeInput, setCodeInput] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [user, setUser] = useState<UserSummary | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [loading, setLoading] = useState(false);
  const [newCode, setNewCode] = useState<string | null>(null);

  const [provider, setProvider] = useState<
    "perplexity" | "openrouter" | "perplexity_web" | "manual"
  >(
    "perplexity",
  );
  const [perplexityApiKey, setPerplexityApiKey] = useState("");
  const [openrouterApiKey, setOpenrouterApiKey] = useState("");
  const [showProviderKeys, setShowProviderKeys] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [manualText, setManualText] = useState("");
  const [analysis, setAnalysis] = useState<ImageAnalysisResult | null>(null);
  const [meals, setMeals] = useState<MealEntry[]>([]);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);

  const [adminOverviewData, setAdminOverviewData] = useState<AdminOverview | null>(null);
  const [adminUsersData, setAdminUsersData] = useState<AdminUser[]>([]);
  const [perplexityWebStatus, setPerplexityWebStatus] =
    useState<ProviderSessionStatus | null>(null);
  const [perplexityConnectEmail, setPerplexityConnectEmail] = useState("");
  const [perplexityConnectPassword, setPerplexityConnectPassword] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    const savedPerplexityKey = window.localStorage.getItem(PERPLEXITY_KEY_STORAGE);
    const savedOpenrouterKey = window.localStorage.getItem(OPENROUTER_KEY_STORAGE);

    if (savedPerplexityKey) {
      setPerplexityApiKey(savedPerplexityKey);
    }
    if (savedOpenrouterKey) {
      setOpenrouterApiKey(savedOpenrouterKey);
    }

    if (!saved) {
      return;
    }

    void loginWithCode(saved, true);
  }, []);

  const title = useMemo(() => {
    if (mode === "admin") {
      return "Admin Console";
    }
    if (mode === "user" && user) {
      return `Hello ${user.name}`;
    }
    return "Calorie Counter";
  }, [mode, user]);

  async function loginWithCode(input: string, silent = false) {
    if (!input) {
      return;
    }

    setLoading(true);
    if (!silent) {
      setNotice(null);
    }

    try {
      const session = await createSession(input.trim());
      if (session.mode === "admin") {
        setMode("admin");
        setAccessCode(input.trim());
        setUser(null);
        setAnalysis(null);
        setNewCode(null);
        window.localStorage.removeItem(STORAGE_KEY);
        await refreshAdmin(input.trim());
        if (!silent) {
          setNotice({ type: "success", text: "Admin access granted." });
        }
        return;
      }

      if (!session.user) {
        throw new Error("Invalid session response");
      }

      setMode("user");
      setAccessCode(input.trim());
      setUser(session.user);
      setNewCode(null);
      window.localStorage.setItem(STORAGE_KEY, input.trim());
      await refreshUserData(input.trim());
      if (!silent) {
        setNotice({ type: "success", text: "You are signed in with your code." });
      }
    } catch (error) {
      setMode("auth");
      setUser(null);
      setAccessCode("");
      setMeals([]);
      setSummary(null);
      setAdminUsersData([]);
      setAdminOverviewData(null);
      setPerplexityWebStatus(null);
      window.localStorage.removeItem(STORAGE_KEY);
      setNotice({
        type: "error",
        text: (error as Error).message || "Code validation failed.",
      });
    } finally {
      setLoading(false);
    }
  }

  async function refreshUserData(code: string) {
    const [summaryData, mealsData] = await Promise.all([
      getSummary(code, 7),
      getMeals(code, 30),
    ]);
    setSummary(summaryData);
    setMeals(mealsData.entries);
  }

  async function refreshAdmin(code: string) {
    const [overviewData, usersData, providerStatus] = await Promise.all([
      adminOverview(code),
      adminUsers(code),
      adminPerplexityWebStatus(code),
    ]);
    setAdminOverviewData(overviewData);
    setAdminUsersData(usersData);
    setPerplexityWebStatus(providerStatus);
  }

  async function handleRegister() {
    setLoading(true);
    setNotice(null);
    try {
      const response = await register(name);
      setName("");
      setNewCode(response.code);
      setCodeInput(response.code);
      await loginWithCode(response.code, true);
      setNotice({ type: "success", text: response.message });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  async function handleAnalyzeImage() {
    if (!accessCode || !imageFile || provider === "manual") {
      return;
    }

    setLoading(true);
    setNotice(null);
    try {
      const result = await analyzePhoto(
        accessCode,
        imageFile,
        provider,
        {
          perplexityApiKey,
          openrouterApiKey,
        },
        true,
      );
      setAnalysis(result);
      await refreshUserData(accessCode);
      setImageFile(null);
      setNotice({ type: "success", text: "Image analyzed and meal saved." });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  async function handleAnalyzeManual() {
    if (!accessCode || !manualText.trim()) {
      return;
    }

    setLoading(true);
    setNotice(null);
    try {
      const result = await analyzeManual(accessCode, manualText, true);
      setAnalysis(result);
      setManualText("");
      await refreshUserData(accessCode);
      setNotice({ type: "success", text: "Manual result parsed and saved." });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteEntry(entryId: number) {
    if (!accessCode) {
      return;
    }

    setLoading(true);
    setNotice(null);
    try {
      await deleteMeal(accessCode, entryId);
      await refreshUserData(accessCode);
      setNotice({ type: "info", text: "Meal removed." });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  async function handleAdminResetCode(userId: number) {
    if (!accessCode) {
      return;
    }

    setLoading(true);
    setNotice(null);
    try {
      const response = await adminResetCode(accessCode, userId);
      setNewCode(response.new_code);
      await refreshAdmin(accessCode);
      setNotice({
        type: "success",
        text: `New code generated for ${response.user.name}. Save it now.`,
      });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  async function handleAdminDeleteUser(userId: number, userName: string) {
    if (!accessCode) {
      return;
    }

    if (!window.confirm(`Delete ${userName} and all meal entries?`)) {
      return;
    }

    setLoading(true);
    setNotice(null);
    try {
      await adminDeleteUser(accessCode, userId);
      await refreshAdmin(accessCode);
      setNotice({ type: "info", text: `${userName} was removed.` });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  function handleLogout() {
    setMode("auth");
    setUser(null);
    setAccessCode("");
    setAnalysis(null);
    setMeals([]);
    setSummary(null);
    setAdminOverviewData(null);
    setAdminUsersData([]);
    setPerplexityWebStatus(null);
    setPerplexityConnectEmail("");
    setPerplexityConnectPassword("");
    setNotice({ type: "info", text: "Logged out." });
    window.localStorage.removeItem(STORAGE_KEY);
  }

  function onImageChange(event: ChangeEvent<HTMLInputElement>) {
    setImageFile(event.target.files?.[0] ?? null);
  }

  function copyManualPrompt() {
    void navigator.clipboard.writeText(MANUAL_PROMPT);
    setNotice({ type: "info", text: "Prompt copied." });
  }

  function handleSaveProviderKeys() {
    window.localStorage.setItem(PERPLEXITY_KEY_STORAGE, perplexityApiKey.trim());
    window.localStorage.setItem(OPENROUTER_KEY_STORAGE, openrouterApiKey.trim());
    setNotice({
      type: "success",
      text: "Provider keys saved in this browser for automatic analysis.",
    });
  }

  async function handleAdminConnectPerplexityWeb() {
    if (!accessCode) {
      return;
    }
    if (!perplexityConnectEmail.trim() || !perplexityConnectPassword.trim()) {
      setNotice({ type: "error", text: "Email and password are required." });
      return;
    }

    setLoading(true);
    setNotice(null);
    try {
      const status = await adminConnectPerplexityWeb(
        accessCode,
        perplexityConnectEmail.trim(),
        perplexityConnectPassword,
      );
      setPerplexityWebStatus(status);
      setPerplexityConnectPassword("");
      setNotice({ type: "success", text: "Perplexity Web session connected." });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  async function handleAdminDisconnectPerplexityWeb() {
    if (!accessCode) {
      return;
    }
    if (!window.confirm("Disconnect the Perplexity Web session?")) {
      return;
    }

    setLoading(true);
    setNotice(null);
    try {
      await adminDisconnectPerplexityWeb(accessCode);
      await refreshAdmin(accessCode);
      setNotice({ type: "info", text: "Perplexity Web session disconnected." });
    } catch (error) {
      setNotice({ type: "error", text: (error as Error).message });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="hero">
        <p className="eyebrow">No signup. Just your private code.</p>
        <h1>{title}</h1>
        <p>
          Photo-first calorie tracker with AI nutrient estimation. Data is stored in SQLite,
          and food photos are analyzed without being stored.
        </p>
      </header>

      {notice && <p className={`notice ${notice.type}`}>{notice.text}</p>}

      {newCode && (
        <section className="panel highlight">
          <h2>Save this code now</h2>
          <p>This code is shown once. Keep it safe to re-enter the app later.</p>
          <div className="code-box">{newCode}</div>
        </section>
      )}

      {mode === "auth" && (
        <section className="grid auth-grid">
          <article className="panel">
            <h2>Create Profile</h2>
            <p>Enter only your name. We generate a private access code immediately.</p>
            <label className="field-label" htmlFor="name-input">
              Name
            </label>
            <input
              id="name-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Maya"
            />
            <button onClick={handleRegister} disabled={loading || !name.trim()}>
              Create and get code
            </button>
          </article>

          <article className="panel">
            <h2>Use Existing Code</h2>
            <p>Open the app anytime by entering your saved code.</p>
            <label className="field-label" htmlFor="code-input">
              Access Code
            </label>
            <input
              id="code-input"
              value={codeInput}
              onChange={(event) => setCodeInput(event.target.value)}
              placeholder="ABCD-EFGH-IJKL-MNOP"
            />
            <button onClick={() => loginWithCode(codeInput)} disabled={loading || !codeInput.trim()}>
              Enter app
            </button>
          </article>
        </section>
      )}

      {mode === "user" && user && (
        <>
	          <section className="grid stat-grid">
            <article className="panel compact">
              <h3>7-day Calories</h3>
              <p className="stat">{Math.round(summary?.calories_kcal ?? 0)} kcal</p>
            </article>
            <article className="panel compact">
              <h3>7-day Protein</h3>
              <p className="stat">{Math.round(summary?.protein_g ?? 0)} g</p>
            </article>
            <article className="panel compact">
              <h3>7-day Fiber</h3>
              <p className="stat">{Math.round(summary?.fiber_g ?? 0)} g</p>
            </article>
            <article className="panel compact">
              <h3>Entries</h3>
              <p className="stat">{summary?.entries ?? 0}</p>
            </article>
          </section>

          <section className="grid app-grid">
            <article className="panel">
              <div className="panel-head">
                <h2>Analyze Food</h2>
                <button className="ghost" onClick={handleLogout}>
                  Log out
                </button>
              </div>

              <p className="small">
                Profile: <strong>{user.name}</strong> · Code hint: ****-{user.code_hint}
              </p>

              <label className="field-label" htmlFor="provider-select">
                Analysis Method
              </label>
              <select
                id="provider-select"
                value={provider}
                onChange={(event) => setProvider(event.target.value as typeof provider)}
              >
                <option value="perplexity">Perplexity API</option>
                <option value="perplexity_web">Perplexity Web (headless session)</option>
                <option value="openrouter">OpenRouter free vision model</option>
                <option value="manual">Perplexity web manual paste</option>
              </select>

              <div className="provider-settings">
                <button
                  className="ghost"
                  onClick={() => setShowProviderKeys((current) => !current)}
                >
                  {showProviderKeys ? "Hide provider keys" : "Add provider keys"}
	                </button>
	                <p className="small">
	                  For `Perplexity Web (headless session)`, an admin must connect a server-side
	                  Playwright session in the Admin Console.
	                </p>
	                {showProviderKeys && (
	                  <div className="manual-block">
                    <label className="field-label" htmlFor="perplexity-key">
                      Perplexity API Key
                    </label>
                    <input
                      id="perplexity-key"
                      type="password"
                      value={perplexityApiKey}
                      onChange={(event) => setPerplexityApiKey(event.target.value)}
                      placeholder="pplx-..."
                    />

                    <label className="field-label" htmlFor="openrouter-key">
                      OpenRouter API Key (optional)
                    </label>
                    <input
                      id="openrouter-key"
                      type="password"
                      value={openrouterApiKey}
                      onChange={(event) => setOpenrouterApiKey(event.target.value)}
                      placeholder="sk-or-..."
                    />
	                    <button className="ghost" onClick={handleSaveProviderKeys}>
	                      Save keys in browser
	                    </button>
	                  </div>
	                )}
	              </div>

              {provider !== "manual" && (
                <>
                  <label className="field-label" htmlFor="file-input">
                    Dish Photo
                  </label>
                  <input
                    id="file-input"
                    type="file"
                    accept="image/*"
                    capture="environment"
                    onChange={onImageChange}
                  />
                  <button onClick={handleAnalyzeImage} disabled={loading || !imageFile}>
                    Analyze and save meal
                  </button>
                </>
              )}

              {provider === "manual" && (
                <div className="manual-block">
                  <p className="small">
                    Upload your photo on Perplexity web, then paste its JSON response below.
                  </p>
                  <textarea readOnly value={MANUAL_PROMPT} />
                  <button className="ghost" onClick={copyManualPrompt}>
                    Copy prompt
                  </button>
                  <textarea
                    placeholder="Paste Perplexity JSON response"
                    value={manualText}
                    onChange={(event) => setManualText(event.target.value)}
                  />
                  <button onClick={handleAnalyzeManual} disabled={loading || !manualText.trim()}>
                    Parse and save meal
                  </button>
                </div>
              )}
            </article>

            <article className="panel">
              <h2>Latest Analysis</h2>
              {!analysis && <p>No analysis yet.</p>}
              {analysis && (
                <div className="result-grid">
                  <div>
                    <span className="label">Dish</span>
                    <p>{analysis.dish}</p>
                  </div>
                  <div>
                    <span className="label">Calories</span>
                    <p>{analysis.calories_kcal ?? "N/A"} kcal</p>
                  </div>
                  <div>
                    <span className="label">Protein</span>
                    <p>{analysis.protein_g ?? "N/A"} g</p>
                  </div>
                  <div>
                    <span className="label">Fiber</span>
                    <p>{analysis.fiber_g ?? "N/A"} g</p>
                  </div>
                  <div>
                    <span className="label">Nutrients</span>
                    <p>{analysis.nutrients.join(", ") || "N/A"}</p>
                  </div>
                  <div>
                    <span className="label">Chemicals</span>
                    <p>{analysis.chemicals.join(", ") || "N/A"}</p>
                  </div>
                  {analysis.notes && (
                    <div>
                      <span className="label">Notes</span>
                      <p>{analysis.notes}</p>
                    </div>
                  )}
                  <div>
                    <span className="label">Provider</span>
                    <p>
                      {analysis.source}
                      {analysis.model ? ` · ${analysis.model}` : ""}
                    </p>
                  </div>
                </div>
              )}
            </article>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Meal History</h2>
              <button className="ghost" onClick={() => refreshUserData(accessCode)}>
                Refresh
              </button>
            </div>
            {!meals.length && <p>No meals yet. Analyze your first dish photo.</p>}
            {!!meals.length && (
              <div className="history-list">
                {meals.map((entry) => (
                  <article className="history-item" key={entry.id}>
                    <div>
                      <h3>{entry.dish}</h3>
                      <p className="small">
                        {new Date(entry.eaten_at).toLocaleString()} · {entry.source} ·{" "}
                        {entry.meal_type}
                      </p>
                      <p className="small">
                        {entry.calories_kcal ?? "N/A"} kcal · {entry.protein_g ?? "N/A"} g protein ·{" "}
                        {entry.fiber_g ?? "N/A"} g fiber
                      </p>
                    </div>
                    <button className="ghost" onClick={() => handleDeleteEntry(entry.id)}>
                      Delete
                    </button>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {mode === "admin" && (
        <>
          <section className="grid stat-grid">
            <article className="panel compact">
              <h3>Total Users</h3>
              <p className="stat">{adminOverviewData?.users ?? 0}</p>
            </article>
            <article className="panel compact">
              <h3>Total Entries</h3>
              <p className="stat">{adminOverviewData?.entries ?? 0}</p>
            </article>
            <article className="panel compact">
              <h3>Total Calories</h3>
              <p className="stat">{Math.round(adminOverviewData?.calories_kcal ?? 0)} kcal</p>
            </article>
	          </section>

	          <section className="panel">
	            <div className="panel-head">
	              <h2>Perplexity Web Session</h2>
	              <div className="action-row">
	                <button className="ghost" onClick={() => refreshAdmin(accessCode)}>
	                  Refresh
	                </button>
	                <button
	                  className="ghost danger"
	                  onClick={handleAdminDisconnectPerplexityWeb}
	                  disabled={!perplexityWebStatus?.connected}
	                >
	                  Disconnect
	                </button>
	              </div>
	            </div>
	            <p className="small">
	              Status:{" "}
	              <strong>{perplexityWebStatus?.connected ? "Connected" : "Not connected"}</strong>
	              {perplexityWebStatus?.updated_at
	                ? ` · Updated ${new Date(perplexityWebStatus.updated_at).toLocaleString()}`
	                : ""}
	            </p>
	            <div className="manual-block">
	              <p className="small">
	                This enables <strong>Perplexity Web (headless session)</strong> analysis without
	                pasting tokens or JSON. Credentials are used only to establish the session and
	                are not stored.
	              </p>
	              <label className="field-label" htmlFor="pplx-connect-email">
	                Perplexity Email
	              </label>
	              <input
	                id="pplx-connect-email"
	                type="email"
	                value={perplexityConnectEmail}
	                onChange={(event) => setPerplexityConnectEmail(event.target.value)}
	                placeholder="you@example.com"
	              />
	              <label className="field-label" htmlFor="pplx-connect-password">
	                Perplexity Password
	              </label>
	              <input
	                id="pplx-connect-password"
	                type="password"
	                value={perplexityConnectPassword}
	                onChange={(event) => setPerplexityConnectPassword(event.target.value)}
	                placeholder="Your Perplexity password"
	              />
	              <button onClick={handleAdminConnectPerplexityWeb} disabled={loading}>
	                Connect session
	              </button>
	              <p className="small">
	                If Perplexity enforces captcha/2FA, headless login can fail; use the{" "}
	                <strong>Perplexity API</strong> mode in that case.
	              </p>
	            </div>
	          </section>

	          <section className="panel">
	            <div className="panel-head">
	              <h2>User Management</h2>
	              <div className="action-row">
                <button className="ghost" onClick={() => refreshAdmin(accessCode)}>
                  Refresh
                </button>
                <button className="ghost" onClick={handleLogout}>
                  Exit admin
                </button>
              </div>
            </div>

            {!adminUsersData.length && <p>No users yet.</p>}
            {!!adminUsersData.length && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Code Hint</th>
                      <th>Entries</th>
                      <th>Calories</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {adminUsersData.map((row) => (
                      <tr key={row.id}>
                        <td>{row.name}</td>
                        <td>****-{row.code_hint}</td>
                        <td>{row.entries}</td>
                        <td>{Math.round(row.calories_kcal)} kcal</td>
                        <td>
                          <div className="action-row">
                            <button
                              className="ghost"
                              onClick={() => handleAdminResetCode(row.id)}
                            >
                              Reset code
                            </button>
                            <button
                              className="ghost danger"
                              onClick={() => handleAdminDeleteUser(row.id, row.name)}
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
