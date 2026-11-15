/**
 * Portfolio Web Grupo 11 (UFABC Q3/2026) - Modulo Base (Secoes 1 a 3)
 * Hidrata telemetria Gold de ./data/processed/po_penalties_mart.json,
 * renderiza equacoes KaTeX e gerencia componentes acessiveis (navbar, tabs, switch, ETL e verificador PL).
 */

(() => {
  "use strict";

  const MART_URL = "./data/processed/po_penalties_mart.json";
  const ZONES = ["L", "C", "R"];
  const ZONE_LABELS = {
    L: "Esquerda (L)",
    C: "Centro (C)",
    R: "Direita (R)",
  };

  const PIPELINE_STAGES = {
    bronze: {
      tag: "Estagio selecionado: 1. Bronze",
      title: "Camada Bronze: po_bronze.raw_kaggle_penalties_sofascore",
      summary:
        "Ingestao bruta via API Kaggle sem perda de colunas (16.629 linhas, 27 colunas originais) carregada por Batch Load gratuito no BigQuery.",
      details: [
        "Script: src/etl/extract_load_bronze.py",
        "Governanca: labels aplicados via LoadJobConfig e confirmados explicitamente na tabela via client.update_table (datacloud=antigravity, domain=po, layer=bronze).",
        "Contrato TC-E2-01B: zero perda de registros entre o CSV local e a tabela na nuvem.",
      ],
    },
    "silver-base": {
      tag: "Estagio selecionado: 2. Silver Base",
      title: "Camada Silver Base: Filtro de Dominio e Normalizacao Espacial",
      summary:
        "Expurgo rigoroso de 903 registros de handebol (14 equipes misturadas na fonte Kaggle), restando exatamente 15.726 cobrancas de futebol.",
      details: [
        "Script: src/etl/transform_silver_base.py",
        "Espelhamento da baliza: lados opostos de campo (x=0 vs x=100) convertidos para o referencial unico do cobrador.",
        "Resultado: classificacao espacial padronizada de shot_zone e gk_zone nas tres faixas horizontais L, C e R.",
      ],
    },
    "silver-enriched": {
      tag: "Estagio selecionado: 3. Silver Enriquecida",
      title: "Camada Silver Enriquecida: Amostra Espacial Completa (1.377 lances)",
      summary:
        "Classifica o evento Nao-Gol em defesas diretas (143) vs. chutes fora/trave (58), somando 201 falhas de conversao (14,60%), e imputa o pe dominante em 100% da amostra espacial.",
      details: [
        "Script: src/etl/enrich_silver_features.py",
        "Distribuicao de pe dominante: 996 destros (right-foot) e 381 canhotos (left-foot), zero nulos.",
        "Clusterizacao idempotente por (has_spatial_coords, shot_zone, gk_zone) preservada em po_silver.stg_football_penalties_clean.",
      ],
    },
    gold: {
      tag: "Estagio selecionado: 4. Gold & JSON",
      title: "Camada Gold: Solver Primal-Dual 3x3, Sensibilidade theta e Scouting",
      summary:
        "Resolve os 6 cenarios taticos com gap Primal-Dual < 1e-9, calcula 66 pontos parametricos theta em [0, 1] e consolida 10 atletas de elite com Empirical Bayes (alpha=5.0).",
      details: [
        "Scripts: src/models/lp_nash_solver.py + src/models/sensitivity_and_scouting.py",
        "Tabelas Gold: mart_payoff_matrices_3x3, mart_sensitivity_theta e mart_shooter_scouting.",
        "Validacao externa: exportacao cruzada Excel Simplex LP (docs/validacao_excel_solver.xlsx) e artefato web JSON.",
      ],
    },
  };

  function escapeHtml(raw) {
    return String(raw)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtPct(ratio, decimals = 2) {
    return `${(Number(ratio) * 100).toFixed(decimals).replace(".", ",")}%`;
  }

  function fmtInt(num) {
    return Number(num).toLocaleString("pt-BR");
  }

  function renderMath(root = document.body) {
    if (typeof window.renderMathInElement !== "function" || !root) {
      return;
    }
    window.renderMathInElement(root, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\(", right: "\\)", display: false },
      ],
      throwOnError: false,
      strict: "ignore",
    });
  }

  function setupThemeSwitch() {
    const input = document.getElementById("theme-switch");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    if (!("switch" in HTMLInputElement.prototype)) {
      input.classList.add("is-switch-fallback");
    }

    let saved = null;
    try {
      saved = window.localStorage.getItem("po-theme");
    } catch (_err) {
      saved = null;
    }
    const prefersDark =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = saved ? saved === "dark" : prefersDark;
    input.checked = isDark;
    if (saved) {
      document.documentElement.dataset.theme = saved;
    }

    input.addEventListener("change", () => {
      const next = input.checked ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      try {
        window.localStorage.setItem("po-theme", next);
      } catch (_err) {
        // Ignora indisponibilidade de storage em modo privado/sandbox.
      }
    });
  }

  function setupNavbar() {
    const header = document.getElementById("site-header");
    const headerInner = header?.querySelector(".header-inner");
    const menuButton = header?.querySelector(".menu-button");
    const siteMenu = document.getElementById("site-menu");
    if (!header || !headerInner || !menuButton || !siteMenu) {
      return;
    }

    const supportsPopover = Object.hasOwn(HTMLElement.prototype, "popover");
    let collapsedWidth = 0;

    function syncMenuLayout(forceMeasure = false) {
      const currentlyWide = header.classList.contains("is-wide");
      const currentWidth = header.getBoundingClientRect().width;
      if (!forceMeasure && !currentlyWide && currentWidth <= collapsedWidth) {
        return;
      }

      const wasOpen =
        supportsPopover && siteMenu.hasAttribute("popover")
          ? siteMenu.matches(":popover-open")
          : siteMenu.classList.contains("is-popover-fallback-open");

      header.classList.add("is-measuring", "is-wide");
      siteMenu.removeAttribute("popover");
      const fitsInline = headerInner.scrollWidth <= headerInner.clientWidth;

      if (fitsInline) {
        collapsedWidth = 0;
        siteMenu.classList.remove("is-popover-fallback-open");
        menuButton.setAttribute("aria-expanded", "false");
      } else {
        header.classList.remove("is-wide");
        collapsedWidth = currentWidth;
        if (supportsPopover) {
          siteMenu.setAttribute("popover", "auto");
          if (wasOpen && typeof siteMenu.showPopover === "function") {
            siteMenu.showPopover();
          }
        } else {
          siteMenu.removeAttribute("popover");
          siteMenu.classList.toggle("is-popover-fallback-open", wasOpen);
        }
        menuButton.setAttribute("aria-expanded", String(wasOpen));
      }

      window.requestAnimationFrame(() => {
        header.classList.remove("is-measuring");
      });
    }

    if (supportsPopover) {
      siteMenu.addEventListener("toggle", (event) => {
        if (!header.classList.contains("is-wide")) {
          menuButton.setAttribute("aria-expanded", String(event.newState === "open"));
        }
      });
    } else {
      menuButton.addEventListener("click", () => {
        const open = !siteMenu.classList.contains("is-popover-fallback-open");
        siteMenu.classList.toggle("is-popover-fallback-open", open);
        menuButton.setAttribute("aria-expanded", String(open));
      });
    }

    const navLinks = Array.from(siteMenu.querySelectorAll('a[href^="#"]'));
    navLinks.forEach((link) => {
      link.addEventListener("click", () => {
        navLinks.forEach((item) => item.removeAttribute("aria-current"));
        link.setAttribute("aria-current", "page");
        if (!header.classList.contains("is-wide")) {
          if (supportsPopover && siteMenu.matches(":popover-open")) {
            siteMenu.hidePopover();
          } else {
            siteMenu.classList.remove("is-popover-fallback-open");
            menuButton.setAttribute("aria-expanded", "false");
          }
        }
      });
    });

    if (typeof window.ResizeObserver === "function") {
      const ro = new ResizeObserver(() => syncMenuLayout(false));
      ro.observe(header);
      ro.observe(siteMenu);
    }
    syncMenuLayout(true);

    if (typeof window.IntersectionObserver === "function") {
      const sections = navLinks
        .map((a) => document.querySelector(a.getAttribute("href")))
        .filter(Boolean);
      const secObserver = new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
          if (!visible) {
            return;
          }
          const activeHref = `#${visible.target.id}`;
          navLinks.forEach((link) => {
            if (link.getAttribute("href") === activeHref) {
              link.setAttribute("aria-current", "page");
            } else {
              link.removeAttribute("aria-current");
            }
          });
        },
        { rootMargin: "-25% 0px -55% 0px", threshold: [0.05, 0.25, 0.6] }
      );
      sections.forEach((sec) => secObserver.observe(sec));
    }
  }

  function setupPersonaTabs() {
    const tabRoot = document.getElementById("persona-tabs");
    if (!tabRoot) {
      return;
    }
    const tabs = Array.from(tabRoot.querySelectorAll('[role="tab"]'));
    const panels = Array.from(tabRoot.querySelectorAll('[role="tabpanel"]'));
    const supportsNativeFocusgroup = Object.hasOwn(HTMLElement.prototype, "focusGroup");

    function selectTab(targetTab, shouldFocus = false) {
      tabs.forEach((tab) => {
        const active = tab === targetTab;
        tab.setAttribute("aria-selected", String(active));
        tab.toggleAttribute("focusgroupstart", active);
        if (!supportsNativeFocusgroup) {
          tab.setAttribute("tabindex", active ? "0" : "-1");
        }
      });

      panels.forEach((panel) => {
        const isActive = panel.getAttribute("aria-labelledby") === targetTab.id;
        if (isActive) {
          panel.removeAttribute("hidden");
          panel.setAttribute("tabindex", "0");
        } else {
          panel.setAttribute("hidden", "until-found");
          panel.removeAttribute("tabindex");
        }
      });

      targetTab.scrollIntoView({ block: "nearest", inline: "nearest" });
      if (shouldFocus) {
        targetTab.focus();
      }
    }

    tabs.forEach((tab, idx) => {
      tab.addEventListener("click", () => selectTab(tab, false));

      tab.addEventListener("keydown", (event) => {
        if (supportsNativeFocusgroup) {
          return;
        }
        let nextIndex = null;
        if (event.key === "ArrowRight") {
          nextIndex = (idx + 1) % tabs.length;
        } else if (event.key === "ArrowLeft") {
          nextIndex = (idx - 1 + tabs.length) % tabs.length;
        } else if (event.key === "Home") {
          nextIndex = 0;
        } else if (event.key === "End") {
          nextIndex = tabs.length - 1;
        }
        if (nextIndex !== null) {
          event.preventDefault();
          selectTab(tabs[nextIndex], true);
        }
      });
    });

    panels.forEach((panel) => {
      panel.addEventListener("beforematch", () => {
        const matchingTab = tabs.find((t) => t.id === panel.getAttribute("aria-labelledby"));
        if (matchingTab) {
          selectTab(matchingTab, false);
        }
      });
    });
  }

  function renderPipelineStage(stageKey) {
    const info = PIPELINE_STAGES[stageKey];
    const tagEl = document.getElementById("etl-selected-tag");
    const boxEl = document.getElementById("pipeline-inspector");
    if (!info || !tagEl || !boxEl) {
      return;
    }
    tagEl.textContent = info.tag;
    const listHtml = info.details.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    boxEl.innerHTML = `
      <h4>${escapeHtml(info.title)}</h4>
      <p>${escapeHtml(info.summary)}</p>
      <ul class="detail-list">${listHtml}</ul>
    `;
  }

  function setupMedallionPipeline() {
    const buttons = Array.from(document.querySelectorAll(".pipeline-step-btn[data-stage]"));
    if (!buttons.length) {
      return;
    }
    renderPipelineStage("bronze");
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const stageKey = btn.dataset.stage;
        buttons.forEach((other) => other.setAttribute("aria-pressed", String(other === btn)));
        renderPipelineStage(stageKey);
      });
    });
  }

  function renderVerifierScenario(scenario) {
    const metricsEl = document.getElementById("theory-verifier-metrics");
    const tbody = document.getElementById("theory-matrix-body");
    const tfoot = document.getElementById("theory-matrix-foot");
    if (!scenario || !metricsEl || !tbody || !tfoot) {
      return;
    }

    const pOpt = [
      Number(scenario.gk_nash_L),
      Number(scenario.gk_nash_C),
      Number(scenario.gk_nash_R),
    ];
    const qOpt = [
      Number(scenario.shooter_nash_L),
      Number(scenario.shooter_nash_C),
      Number(scenario.shooter_nash_R),
    ];
    const vPrimal = Number(scenario.game_value_v_primal);
    const wDual = Number(scenario.game_value_w_dual);

    metricsEl.innerHTML = `
      <div class="mini-stat">
        <span>Cenario / Amostra (n)</span>
        <strong>${escapeHtml(scenario.scenario_code)} (n=${fmtInt(scenario.sample_size)})</strong>
      </div>
      <div class="mini-stat">
        <span>Nao-Gol Empirico</span>
        <strong>${fmtPct(scenario.empirical_non_goal_rate, 2)} (${fmtInt(scenario.total_missed)}/${fmtInt(scenario.sample_size)})</strong>
      </div>
      <div class="mini-stat">
        <span>Valor Otimo Primal (V*)</span>
        <strong>${fmtPct(vPrimal, 2)} (alpha=${Number(scenario.eb_alpha).toFixed(1)})</strong>
      </div>
      <div class="mini-stat">
        <span>Dualidade Forte (W* &amp; Gap)</span>
        <strong>${fmtPct(wDual, 2)} | ${Number(scenario.duality_gap).toExponential(2)}</strong>
      </div>
    `;

    tbody.innerHTML = ZONES.map((gkZone, rowIdx) => {
      const cells = ZONES.map((shZone) => {
        const aij = Number(scenario[`a_${gkZone}_${shZone}`]);
        const misses = Number(scenario[`miss_${gkZone}_${shZone}`]);
        const nTotal = Number(scenario[`n_${gkZone}_${shZone}`]);
        return `<td class="stat-cell">${fmtPct(aij, 2)} <small>(${fmtInt(misses)}/${fmtInt(nTotal)})</small></td>`;
      }).join("");
      return `
        <tr>
          <th scope="row">${escapeHtml(ZONE_LABELS[gkZone])} (p*=${fmtPct(pOpt[rowIdx], 1)})</th>
          ${cells}
        </tr>
      `;
    }).join("");

    const colExpectations = ZONES.map((shZone, colIdx) => {
      const expectedVsCorner = ZONES.reduce(
        (acc, gkZone, rowIdx) => acc + pOpt[rowIdx] * Number(scenario[`a_${gkZone}_${shZone}`]),
        0
      );
      const slack = Math.max(0, expectedVsCorner - vPrimal);
      const activeLabel = qOpt[colIdx] > 1e-4 ? "Restricao ativa (q*>0)" : "Folga positiva";
      return `
        <td class="stat-cell">
          <div>Sum p*_i a_ij = <strong>${fmtPct(expectedVsCorner, 2)}</strong></div>
          <small>Folga: ${(slack * 100).toFixed(3)} p.p. | ${activeLabel}</small>
        </td>
      `;
    }).join("");

    tfoot.innerHTML = `
      <tr>
        <th scope="row">Verificacao Primal vs. V* (${fmtPct(vPrimal, 2)})</th>
        ${colExpectations}
      </tr>
    `;
  }

  function hydratePortfolioFromMart(mart) {
    const scenarios = Array.isArray(mart.scenarios) ? mart.scenarios : [];
    const c1 = scenarios.find((item) => item.scenario_code === "C1_GLOBAL") || scenarios[0];
    const scouting = Array.isArray(mart.shooter_scouting) ? mart.shooter_scouting : [];
    const kane = scouting.find((item) => item.player === "Harry Kane") || scouting[0];

    if (c1) {
      const elSpatialDetail = document.querySelector('[data-kpi="spatial-detail"]');
      const elSpatialSub = document.querySelector('[data-kpi="spatial-sub"]');
      const elVstar = document.querySelector('[data-kpi="global-vstar"]');
      const elGap = document.querySelector('[data-kpi="global-gap"]');
      const elCenter = document.querySelector('[data-kpi="global-center"]');
      const elCenterSub = document.querySelector('[data-kpi="global-center-sub"]');

      if (elSpatialDetail) elSpatialDetail.textContent = `${fmtInt(c1.sample_size)} lances`;
      if (elSpatialSub) {
        elSpatialSub.textContent = `143 defesas + 58 fora/trave (${fmtPct(c1.empirical_non_goal_rate, 2)} nao-gol)`;
      }
      if (elVstar) elVstar.textContent = fmtPct(c1.game_value_v_primal, 2);
      if (elGap) {
        elGap.textContent = `Gap Primal-Dual = ${Number(c1.duality_gap).toExponential(2)} (${scenarios.length} cenarios)`;
      }
      if (elCenter) elCenter.textContent = `${fmtPct(c1.gk_nash_C, 1)} C`;
      if (elCenterSub) {
        elCenterSub.textContent = `Corrige sub-cobertura real (${fmtPct(c1.gk_emp_C, 1)} empirico)`;
      }

      const compTrainer = document.getElementById("comp-trainer-global");
      const compGk = document.getElementById("comp-gk-global");
      if (compTrainer) {
        const texPct = (ratio, dec) => fmtPct(ratio, dec).replace(",", "{,}").replace("%", "\\%");
        compTrainer.innerHTML = `\\(p^* = (${texPct(c1.gk_nash_L, 1)}\\;E,\\; ${texPct(c1.gk_nash_C, 1)}\\;C,\\; ${texPct(c1.gk_nash_R, 1)}\\;D)\\), \\(V^* = ${texPct(c1.game_value_v_primal, 2)}\\), gap <code>${escapeHtml(Number(c1.duality_gap).toExponential(2))}</code>.`;
        renderMath(compTrainer);
      }
      if (compGk && kane) {
        compGk.textContent = `Global: ~${Math.round(c1.gk_nash_L * 10)} E / ~${Math.round(c1.gk_nash_C * 10)} C / ~${Math.round(c1.gk_nash_R * 10)} D a cada 10 chutes (ex.: Kane Nash V*=${fmtPct(kane.game_value_v_nash, 2)}).`;
      }
    }

    const statusBadge = document.getElementById("mart-status-badge");
    const sensCount = Array.isArray(mart.sensitivity_curves) ? mart.sensitivity_curves.length : 0;
    if (statusBadge) {
      statusBadge.textContent = `BigQuery Gold sincronizado (${scenarios.length} cenarios | ${sensCount} pts theta | ${scouting.length} atletas)`;
    }

    const goldCoverageEl = document.querySelector('[data-kpi="gold-coverage"]');
    if (goldCoverageEl) {
      goldCoverageEl.textContent = `${sensCount} pts theta | ${scouting.length} atletas`;
    }

    const footerTs = document.getElementById("footer-generated-at");
    if (footerTs && mart.metadata?.generated_at_utc) {
      footerTs.textContent = mart.metadata.generated_at_utc.slice(0, 19).replace("T", " ") + " UTC";
    }

    const selectEl = document.getElementById("theory-scenario-select");
    if (selectEl && scenarios.length) {
      selectEl.innerHTML = scenarios
        .map(
          (sc) =>
            `<option value="${escapeHtml(sc.scenario_code)}">${escapeHtml(sc.scenario_label)}</option>`
        )
        .join("");

      const onChange = () => {
        const chosen = scenarios.find((sc) => sc.scenario_code === selectEl.value) || scenarios[0];
        renderVerifierScenario(chosen);
      };
      selectEl.addEventListener("change", onChange);
      onChange();
    }
  }

  async function loadMartData() {
    const statusBadge = document.getElementById("mart-status-badge");
    if (window.location.protocol === "file:") {
      if (statusBadge) {
        statusBadge.textContent =
          "Visualizacao estatica local (inicie python -m http.server para leitura JSON ao vivo)";
      }
      return;
    }

    try {
      const response = await window.fetch(MART_URL);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ao carregar ${MART_URL}`);
      }
      const mart = await response.json();
      hydratePortfolioFromMart(mart);
    } catch (_err) {
      if (statusBadge) {
        statusBadge.textContent = "Dados Gold em cache estatico (JSON indisponivel)";
      }
    }
  }

  function init() {
    setupThemeSwitch();
    setupNavbar();
    setupPersonaTabs();
    setupMedallionPipeline();
    renderMath();
    void loadMartData();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
