const state = { case: "us_china", result: null, health: null, papers: [], sources: [], slideIndex: 0 };
const byId = (id) => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatPct(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return `${Number(value) > 0 ? "+" : ""}${formatNumber(value, 1)}%`;
}

function money(value) {
  if (!Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0, notation: Number(value) >= 1e9 ? "compact" : "standard" }).format(Number(value));
}

function labelFamily(family) {
  return ({ constant: "Naïve statistical", momentum: "Statistical baseline", seasonal: "Seasonal statistical", linear: "Linear statistical", forest: "Machine learning" })[family] || family;
}

function setStatus(message, mode = "loading") {
  const banner = byId("status-banner");
  banner.className = `status-banner ${mode}`;
  byId("status-message").textContent = message;
  byId("benchmark-content").classList.toggle("hidden", mode === "error" || mode === "loading");
}

async function loadBenchmark() {
  state.case = byId("case-select").value;
  state.result = null;
  byId("review-button").disabled = true;
  byId("review-output").textContent = "";
  setStatus("Loading selected benchmark…", "loading");
  try {
    const response = await fetch(`/api/benchmark?case=${encodeURIComponent(state.case)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The benchmark could not be loaded.");
    state.result = result;
    renderBenchmark(result);
  } catch (error) {
    setStatus(error.message || "The benchmark could not be loaded. Check the server and database settings.", "error");
  }
}

function renderBenchmark(result) {
  const data = result.data || {};
  const status = String(data.status || (data.synthetic ? "synthetic" : data.mode || "unverified")).toLowerCase();
  const statusPresentation = {
    curated: { banner: `Curated observations · ${data.source_label || "Source metadata"}`, css: "real", notice: "These observations are marked curated in the database. Verify the source documentation, revisions, classification mapping, and release dates before interpreting results." },
    unverified: { banner: "Unverified observations · Forecasts are exploratory only.", css: "unverified", notice: "At least one database observation is unverified or lacks a verification status. Do not treat this forecast as an approved research result." },
    mixed: { banner: "Mixed data status · Curated and unverified observations are combined.", css: "unverified", notice: "This series contains a mixture of curated and unverified observations. The model uses the supplied rows, but the result is not eligible for approved forecast storage." },
    synthetic: { banner: "Synthetic preview · These values are fabricated for interface demonstration.", css: "demo", notice: data.note || "Synthetic values are for interface demonstration only; they are not official observations and must not be saved as a research forecast." },
    temporary_upload: { banner: "Temporary upload · Analyzed in memory for this request only.", css: "temporary", notice: data.note || "This uploaded file was analyzed for this request only. It was not saved to PostgreSQL." },
  };
  const presentation = statusPresentation[status] || statusPresentation.unverified;
  setStatus(presentation.banner, presentation.css);
  byId("target-title").textContent = result.target_name || "Monthly trade outcome";
  byId("target-series").textContent = result.target_series || "Monthly data; product-code coverage should be validated.";
  byId("target-month").textContent = result.forecast_target_period || "—";
  byId("last-month").textContent = `Last observed: ${result.last_observed_period || "—"} · ${result.horizon_months || 3}-month horizon`;
  byId("forecast-count").textContent = `${result.comparison_window || 0} origins`;
  byId("metrics-note").textContent = result.metrics_note || "Metrics use the same rolling forecast origins for each model.";
  renderForecasts(result.forecasts || [], result.models || []);
  renderModelTable(result.models || []);
  renderMaeBars(result.models || []);
  renderRegimes(result.regimes || {});
  populateChartChoices(result.models || []);
  renderBacktest(result, byId("chart-model").value || "");
  const notice = byId("data-notice");
  notice.className = `data-notice ${presentation.css}`;
  notice.textContent = data.note || presentation.notice;
  renderCitations(result.source_citations || []);
  resetSlides();
  byId("review-button").disabled = !(state.health && state.health.review_available && result.models && result.models.length);
  byId("benchmark-content").classList.remove("hidden");
}

function renderForecasts(forecasts, models) {
  const container = byId("forecast-cards");
  container.replaceChildren();
  const best = models.length ? models[0].id : null;
  for (const item of forecasts) {
    const card = element("article", `forecast-card${item.id === best ? " best" : ""}`);
    const top = element("div", "forecast-card-top");
    top.append(element("span", "model-name", item.label));
    if (item.id === best) top.append(element("span", "winner-pill", "Lowest backtest MAE"));
    card.append(top);
    const change = element("div", `forecast-change${Number(item.predicted_change_pct) < 0 ? " negative" : ""}`, formatPct(item.predicted_change_pct));
    card.append(change, element("small", "", "Predicted change over the next 3 months"));
    card.append(element("small", "forecast-value", `Implied trade value · ${money(item.implied_value_usd)}`));
    container.append(card);
  }
  if (!forecasts.length) container.append(element("p", "empty-state", "No model forecasts are available for this dataset."));
}

function renderModelTable(models) {
  const body = byId("model-rows");
  body.replaceChildren();
  for (const model of models) {
    const row = document.createElement("tr");
    const name = element("td", "model-cell", model.label);
    const family = document.createElement("td");
    family.append(element("span", "family-pill", labelFamily(model.family)));
    const mae = element("td", "", formatNumber(model.mae_percentage_points));
    const rmse = element("td", "", formatNumber(model.rmse_percentage_points));
    const direction = element("td", "", model.direction_accuracy === null ? "—" : `${formatNumber(model.direction_accuracy * 100, 1)}%`);
    row.append(name, family, mae, rmse, direction);
    body.append(row);
  }
}

function renderRegimes(regimes) {
  byId("latest-cluster").textContent = regimes.latest_feature_cluster ? "Latest features · group " + regimes.latest_feature_cluster : "Exploratory";
  byId("regime-method").textContent = (regimes.method || "Unsupervised descriptive clustering") + " · " + (regimes.feature_count || 0) + " features";
  byId("regime-caveat").textContent = regimes.caveat || "Clusters are descriptive, not forecasts or causal findings.";
  const container = byId("regime-cards");
  container.replaceChildren();
  for (const item of regimes.clusters || []) {
    const card = element("div", "regime-card");
    card.append(element("strong", "", "Group " + item.cluster + " · " + item.description));
    card.append(element("div", "regime-score", formatPct(item.mean_realized_change_pct)));
    card.append(element("small", "", "Mean realized three-month change"));
    card.append(element("div", "regime-count", item.observations + " historical months · retrospective average"));
    container.append(card);
  }
}

function renderMaeBars(models) {
  const container = byId("mae-bars");
  container.replaceChildren();
  const max = Math.max(...models.map((model) => Number(model.mae_percentage_points) || 0), 0.00001);
  for (let index = 0; index < models.length; index += 1) {
    const item = models[index];
    const row = element("div", "mae-item");
    const info = document.createElement("div");
    info.append(element("div", "mae-name", item.label));
    const track = element("div", "bar-track");
    const fill = element("div", `bar-fill${index === 0 ? " best" : ""}`);
    fill.style.width = `${Math.max(2, (Number(item.mae_percentage_points) / max) * 100)}%`;
    track.append(fill);
    info.append(track);
    row.append(info, element("span", "mae-value", formatNumber(item.mae_percentage_points)));
    container.append(row);
  }
}

function populateChartChoices(models) {
  const select = byId("chart-model");
  const previous = select.value;
  select.replaceChildren();
  for (const model of models) {
    const option = element("option", "", model.label);
    option.value = model.id;
    select.append(option);
  }
  if (models.some((model) => model.id === previous)) select.value = previous;
}

function svgElement(tag, attributes = {}, text = null) {
  const node = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== null) node.textContent = String(text);
  return node;
}

function renderBacktest(result, modelId) {
  const holder = byId("backtest-chart");
  holder.replaceChildren();
  const series = result.backtests && result.backtests[modelId];
  if (!series || !series.length) {
    holder.append(element("p", "empty-state", "No backtest rows are available."));
    return;
  }
  const width = 820, height = 220, left = 40, right = 15, top = 15, bottom = 30;
  const allValues = series.flatMap((row) => [Number(row.actual_change_pct), Number(row.predicted_change_pct)]).filter(Number.isFinite);
  let min = Math.min(...allValues), max = Math.max(...allValues);
  if (max === min) { max += 1; min -= 1; }
  const pad = Math.max((max - min) * 0.12, 1);
  min -= pad; max += pad;
  const x = (index) => left + (index / Math.max(series.length - 1, 1)) * (width - left - right);
  const y = (value) => top + ((max - value) / (max - min)) * (height - top - bottom);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Historical forecast values and outcomes" });
  for (let step = 0; step <= 4; step += 1) {
    const value = min + ((max - min) * step) / 4;
    const yy = y(value);
    svg.append(svgElement("line", { x1: left, y1: yy, x2: width - right, y2: yy, stroke: "#e9f0f6", "stroke-width": 1 }));
    svg.append(svgElement("text", { x: left - 7, y: yy + 3, "text-anchor": "end", fill: "#91a0af", "font-size": 9 }, `${value.toFixed(0)}%`));
  }
  const pathFor = (key) => series.map((row, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(Number(row[key])).toFixed(1)}`).join(" ");
  svg.append(svgElement("path", { d: pathFor("actual_change_pct"), fill: "none", stroke: "#287bd2", "stroke-width": 2.2, "stroke-linecap": "round", "stroke-linejoin": "round" }));
  svg.append(svgElement("path", { d: pathFor("predicted_change_pct"), fill: "none", stroke: "#f18b35", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "stroke-dasharray": "5 4" }));
  series.forEach((row, index) => {
    svg.append(svgElement("circle", { cx: x(index), cy: y(Number(row.actual_change_pct)), r: 2.3, fill: "#287bd2" }));
    if (index % Math.max(1, Math.floor(series.length / 7)) === 0 || index === series.length - 1) {
      svg.append(svgElement("text", { x: x(index), y: height - 7, "text-anchor": "middle", fill: "#91a0af", "font-size": 8 }, row.forecast_origin));
    }
  });
  holder.append(svg);
}

function renderCitations(citations) {
  const container = byId("citations");
  container.replaceChildren();
  for (const citation of citations) {
    try {
      const url = new URL(citation.url);
      if (url.protocol !== "https:") continue;
      const link = element("a", "citation-link", `${citation.label} ↗`);
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      container.append(link);
    } catch { /* Ignore malformed source metadata. */ }
  }
}

async function loadPapers() {
  try {
    const query = byId("paper-filter").value;
    const response = await fetch(`/api/papers${query ? `?domain=${encodeURIComponent(query)}` : ""}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Research library unavailable.");
    state.papers = result.papers || [];
    byId("paper-count").textContent = `${state.papers.length} selected papers · ${result.source === "postgresql" ? "PostgreSQL catalogue" : "bundled cited starter catalogue"}`;
    renderPapers(state.papers);
  } catch (error) {
    byId("paper-count").textContent = error.message;
    byId("paper-grid").replaceChildren();
  }
}

function renderPapers(papers) {
  const container = byId("paper-grid");
  container.replaceChildren();
  if (!papers.length) {
    container.append(element("p", "empty-state", "No papers match this domain."));
    return;
  }
  for (const paper of papers) {
    const slug = String(paper.domain || "").toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "");
    const card = element("article", "paper-card");
    const top = element("div", "paper-top");
    top.append(element("span", `domain-tag ${slug}`, paper.domain), element("span", "paper-year", paper.year));
    card.append(top, element("h3", "", paper.title), element("p", "paper-authors", paper.authors), element("p", "paper-relevance", paper.relevance));
    const bottom = element("div", "paper-bottom");
    bottom.append(element("span", "paper-venue", paper.venue));
    try {
      const url = new URL(paper.url);
      if (url.protocol === "https:") {
        const link = element("a", "paper-link", "Open paper ↗");
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        bottom.append(link);
      }
    } catch { /* Do not render an unverified link. */ }
    card.append(bottom);
    container.append(card);
  }
}

async function loadSources() {
  try {
    const response = await fetch("/api/sources");
    const result = await response.json();
    state.sources = result.sources || [];
    const container = byId("source-list");
    container.replaceChildren();
    for (const source of state.sources) {
      const card = element("article", "source-card");
      card.append(element("h3", "", source.title), element("span", "source-provider", `${source.provider} · ${source.frequency || "Source documentation"}`));
      try {
        const url = new URL(source.url);
        if (url.protocol === "https:") {
          const link = element("a", "source-link", "Open source ↗");
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          card.append(link);
        }
      } catch { /* Ignore malformed source metadata. */ }
      card.append(element("span", "source-limit", source.limitations));
      container.append(card);
    }
  } catch {
    byId("source-list").append(element("p", "", "Source registry is unavailable."));
  }
}

async function loadHistory() {
  const holder = byId("history-content");
  try {
    const response = await fetch("/api/history");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Saved history is unavailable.");
    holder.replaceChildren();
    if (!payload.runs || !payload.runs.length) {
      holder.append(element("p", "history-empty", payload.database_configured ? "No approved forecasts have been saved yet." : "Connect PostgreSQL and save a reviewed run to start tracking later outcomes."));
      return;
    }
    const labels = {
      us_exports_cn_854231: "U.S. semiconductor-related exports · China",
    };
    for (const run of payload.runs) {
      const card = element("article", "history-run");
      const header = element("div", "history-run-header");
      const runDate = run.created_at ? new Date(run.created_at).toLocaleDateString() : "Saved run";
      header.append(element("strong", "", labels[run.benchmark_key] || run.benchmark_key));
      header.append(element("span", "history-run-meta", runDate + " · target " + String(run.target_period || "").slice(0, 7) + " · " + run.horizon_months + "-month horizon"));
      card.append(header);
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      ["Model", "Forecast change", "Observed change", "Status"].forEach((label) => headRow.append(element("th", "", label)));
      thead.append(headRow);
      const tbody = document.createElement("tbody");
      for (const item of run.predictions || []) {
        const row = document.createElement("tr");
        row.append(
          element("td", "", item.model_id),
          element("td", "", formatPct(item.predicted_change_pct)),
          element("td", "", item.observed_change_pct === null ? "Awaiting data" : formatPct(item.observed_change_pct)),
          element("td", "", item.evaluation_status === "observed" ? "Evaluated" : "Awaiting outcome"),
        );
        tbody.append(row);
      }
      table.append(thead, tbody);
      const scroll = element("div", "table-scroll");
      scroll.append(table);
      card.append(scroll);
      holder.append(card);
    }
  } catch (error) {
    holder.replaceChildren(element("p", "history-empty", error.message || "Saved history is unavailable."));
  }
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    state.health = await response.json();
    byId("review-button").disabled = !(state.health.review_available && state.result);
  } catch { state.health = null; }
}

async function analyzeUpload() {
  const file = byId("csv-file").files[0];
  const message = byId("upload-message");
  if (!file) return;
  message.className = "upload-message";
  message.textContent = "Reading and analyzing the selected monthly series…";
  byId("analyze-button").disabled = true;
  try {
    const text = await file.text();
    const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ csv_text: text, case: state.case }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Analysis could not be completed.");
    state.result = result;
    renderBenchmark(result);
    message.textContent = "Analysis complete. This file was used only for this request and was not saved.";
    byId("comparison").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    message.className = "upload-message error";
    message.textContent = error.message || "Could not analyze this file. Check the template and monthly coverage.";
  } finally {
    byId("analyze-button").disabled = !byId("csv-file").files.length;
  }
}

async function requestReview() {
  const button = byId("review-button");
  const output = byId("review-output");
  if (!state.result) return;
  button.disabled = true;
  output.textContent = "Reviewing the evaluation setup…";
  try {
    const response = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ result: state.result }) });
    const result = await response.json();
    if (!response.ok || !result.available) throw new Error(result.message || result.error || "Advisory review is not enabled for this deployment.");
    output.textContent = `Advisory only · This review did not change the forecast.\n${result.review}`;
  } catch (error) {
    output.textContent = error.message;
  } finally {
    button.disabled = !(state.health && state.health.review_available);
  }
}

function updateSlides() {
  const slides = Array.from(document.querySelectorAll(".benchmark-slide"));
  const track = byId("slides-track");
  if (!slides.length || !track) return;
  state.slideIndex = Math.max(0, Math.min(state.slideIndex, slides.length - 1));
  const viewport = byId("benchmark-slides");
  track.style.transform = `translate3d(-${state.slideIndex * viewport.clientWidth}px, 0, 0)`;
  const label = slides[state.slideIndex].getAttribute("aria-label") || `Slide ${state.slideIndex + 1}`;
  byId("slide-position").textContent = `Slide ${state.slideIndex + 1} of ${slides.length} · ${label}`;
  byId("slide-prev").disabled = state.slideIndex === 0;
  byId("slide-next").disabled = state.slideIndex === slides.length - 1;
}

function resetSlides() {
  state.slideIndex = 0;
  updateSlides();
}

byId("slide-prev").addEventListener("click", () => {
  state.slideIndex -= 1;
  updateSlides();
});
byId("slide-next").addEventListener("click", () => {
  state.slideIndex += 1;
  updateSlides();
});
window.addEventListener("resize", updateSlides);

byId("case-select").addEventListener("change", loadBenchmark);
byId("chart-model").addEventListener("change", () => state.result && renderBacktest(state.result, byId("chart-model").value));
byId("paper-filter").addEventListener("change", loadPapers);
byId("csv-file").addEventListener("change", () => {
  const file = byId("csv-file").files[0];
  byId("analyze-button").disabled = !file;
  byId("upload-message").textContent = file ? `${file.name} · ${(file.size / 1024).toFixed(1)} KB` : "";
});
byId("analyze-button").addEventListener("click", analyzeUpload);
byId("review-button").addEventListener("click", requestReview);

Promise.all([loadBenchmark(), loadPapers(), loadSources(), loadHealth(), loadHistory()]);
