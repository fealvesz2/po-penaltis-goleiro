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

    setupCoachSection(mart);
  }

  function extractMatrixAndEmpirical(scenario) {
    const A = ZONES.map((gz) => ZONES.map((sz) => Number(scenario[`a_${gz}_${sz}`])));
    const qEmp = ZONES.map((sz) => Number(scenario[`shooter_emp_${sz}`]));
    const empReturns = A.map((row) => row[0] * qEmp[0] + row[1] * qEmp[1] + row[2] * qEmp[2]);
    return { A, qEmp, empReturns };
  }

  function solveZeroSum3x3(A) {
    const shift = 1.0;
    const T = [0, 1, 2].map((i) => [
      A[i][0] + shift,
      A[i][1] + shift,
      A[i][2] + shift,
      i === 0 ? 1 : 0,
      i === 1 ? 1 : 0,
      i === 2 ? 1 : 0,
      1.0,
    ]);
    T.push([-1, -1, -1, 0, 0, 0, 0]);
    const basis = [3, 4, 5];

    for (let iter = 0; iter < 30; iter++) {
      let enter = -1;
      for (let c = 0; c < 6; c++) {
        if (T[3][c] < -1e-12) {
          enter = c;
          break;
        }
      }
      if (enter === -1) break;

      let leave = -1;
      let bestRatio = Infinity;
      for (let r = 0; r < 3; r++) {
        const a = T[r][enter];
        if (a > 1e-12) {
          const ratio = T[r][6] / a;
          if (
            ratio < bestRatio - 1e-12 ||
            (Math.abs(ratio - bestRatio) <= 1e-12 && basis[r] < basis[leave])
          ) {
            bestRatio = ratio;
            leave = r;
          }
        }
      }
      if (leave === -1) break;

      const piv = T[leave][enter];
      for (let c = 0; c < 7; c++) T[leave][c] /= piv;
      for (let r = 0; r < 4; r++) {
        if (r === leave) continue;
        const factor = T[r][enter];
        if (Math.abs(factor) < 1e-15) continue;
        for (let c = 0; c < 7; c++) T[r][c] -= factor * T[leave][c];
      }
      basis[leave] = enter;
    }

    const sumVal = T[3][6] || 1;
    const x = [T[3][3], T[3][4], T[3][5]].map((val) => Math.max(0, val));
    const sumX = x.reduce((acc, val) => acc + val, 0) || 1;
    const p = x.map((val) => val / sumX);

    const y = [0, 0, 0];
    for (let r = 0; r < 3; r++) {
      if (basis[r] < 3) y[basis[r]] = Math.max(0, T[r][6]);
    }
    const sumY = y.reduce((acc, val) => acc + val, 0) || 1;
    const q = y.map((val) => val / sumY);
    return { p, q, vStar: 1.0 / sumVal - shift };
  }

  function evaluateCoachAtTheta(scenario, theta) {
    const t = Math.min(1, Math.max(0, Number(theta) || 0));
    const { A, qEmp, empReturns } = extractMatrixAndEmpirical(scenario);
    const ATheta = A.map((row, i) => row.map((a) => t * empReturns[i] + (1 - t) * a));
    const solved = solveZeroSum3x3(ATheta);
    const evVsEmp = solved.p.reduce((acc, pi, i) => acc + pi * empReturns[i], 0);
    const cornerTrue = ZONES.map((_, j) =>
      solved.p.reduce((acc, pi, i) => acc + pi * A[i][j], 0)
    );
    const worstFloor = Math.min(...cornerTrue);
    const cornerHybrid = ZONES.map((_, j) =>
      solved.p.reduce((acc, pi, i) => acc + pi * ATheta[i][j], 0)
    );
    const vNash = Number(scenario.game_value_v_primal);
    const bestEmpIdx = empReturns.indexOf(Math.max(...empReturns));
    return {
      theta: t,
      A,
      ATheta,
      qEmp,
      empReturns,
      p: solved.p,
      qTilde: solved.q,
      vStar: solved.vStar,
      vNash,
      upliftVsNash: solved.vStar - vNash,
      evVsEmp,
      worstFloor,
      floorDrop: Math.max(0, vNash - worstFloor),
      cornerTrue,
      cornerHybrid,
      bestEmpCorner: ZONES[bestEmpIdx],
      bestEmpRate: empReturns[bestEmpIdx],
    };
  }

  function buildScenarioCurveData(scenario) {
    const points = [];
    for (let k = 0; k <= 100; k++) {
      const t = Number((k / 100).toFixed(2));
      const snap = evaluateCoachAtTheta(scenario, t);
      points.push({
        theta: t,
        vStar: snap.vStar,
        evVsEmp: snap.evVsEmp,
        worstFloor: snap.worstFloor,
        p: snap.p,
      });
    }
    const vNash = Number(scenario.game_value_v_primal);
    let critPoint = points.find((pt) => vNash - pt.worstFloor > 0.005);
    if (!critPoint) {
      const pNash = ZONES.map((z) => Number(scenario[`gk_nash_${z}`]));
      critPoint = points.find((pt) =>
        pt.p.some((pi, idx) => Math.abs(pi - pNash[idx]) > 0.02)
      );
    }
    const criticalTheta = critPoint ? critPoint.theta : 1.0;
    const minRate = Math.min(...points.map((pt) => pt.worstFloor));
    const maxRate = Math.max(...points.map((pt) => Math.max(pt.vStar, pt.evVsEmp)));
    return {
      points,
      criticalTheta,
      minRate,
      maxRate,
      empEnd: points[points.length - 1],
    };
  }

  function syncSliderVars(slider) {
    if (!slider) return;
    slider.style.setProperty("--attr-min", slider.min || "0");
    slider.style.setProperty("--attr-max", slider.max || "1");
    slider.style.setProperty("--control-value", slider.value);
  }

  function renderCoachKpis(scenario, snap, curveInfo) {
    const kpisEl = document.getElementById("coach-kpis");
    if (!kpisEl) return;

    const isProtected = snap.floorDrop <= 0.005;
    const regimeClass = isProtected ? "mini-stat-safe" : "mini-stat-alert";
    const badgeClass = isProtected ? "regime-pill-safe" : "regime-pill-alert";
    const badgeText = isProtected ? "Protegido (Minimax)" : "Alerta Exploratorio";
    const upliftPp = (snap.upliftVsNash * 100).toFixed(2).replace(".", ",");
    const dropPp = (snap.floorDrop * 100).toFixed(2).replace(".", ",");
    const critLabel = curveInfo.criticalTheta.toFixed(2).replace(".", ",");

    kpisEl.innerHTML = `
      <div class="mini-stat">
        <span>Valor do Jogo V*(theta)</span>
        <strong>${fmtPct(snap.vStar, 2)}</strong>
        <small class="control-hint">+${upliftPp} p.p. vs Nash V*(0)=${fmtPct(snap.vNash, 2)}</small>
      </div>
      <div class="mini-stat">
        <span>Expectativa vs. Scouting (E_emp)</span>
        <strong>${fmtPct(snap.evVsEmp, 2)}</strong>
        <small class="control-hint">Teto maximo puro (${escapeHtml(snap.bestEmpCorner)}): ${fmtPct(snap.bestEmpRate, 2)}</small>
      </div>
      <div class="mini-stat ${regimeClass}">
        <span>Piso de Pior Cenario Fl(p*)</span>
        <strong>${fmtPct(snap.worstFloor, 2)}</strong>
        <span class="regime-pill ${badgeClass}">${badgeText}</span>
        <small class="control-hint">${isProtected ? "Garantia preservada sem brecha" : `Queda de ${dropPp} p.p. se batedor adaptar`}</small>
      </div>
      <div class="mini-stat">
        <span>Fronteira de Ruptura (theta_crit)</span>
        <strong>theta = ${critLabel}</strong>
        <small class="control-hint">${snap.theta < curveInfo.criticalTheta ? "Abaixo da ruptura: mantenha Nash" : "Acima da ruptura: mistura exploratoria"}</small>
      </div>
    `;
  }

  function renderCoachMixPanel(scenario, snap) {
    const mixEl = document.getElementById("coach-mix-panel");
    if (!mixEl) return;

    const pNash = [
      Number(scenario.gk_nash_L),
      Number(scenario.gk_nash_C),
      Number(scenario.gk_nash_R),
    ];

    const barsHtml = ZONES.map((zone, idx) => {
      const pctCur = (snap.p[idx] * 100).toFixed(1);
      const pctNash = (pNash[idx] * 100).toFixed(1);
      const diffPp = ((snap.p[idx] - pNash[idx]) * 100).toFixed(1);
      const diffSigned = `${Number(diffPp) >= 0 ? "+" : ""}${diffPp.replace(".", ",")} p.p.`;
      return `
        <div class="mix-bar-card">
          <div class="mix-bar-top">
            <span>${escapeHtml(ZONE_LABELS[zone])}</span>
            <strong>${fmtPct(snap.p[idx], 1)}</strong>
          </div>
          <div class="mix-track" aria-hidden="true">
            <div class="mix-fill" style="inline-size: ${pctCur}%"></div>
            <div class="mix-nash-ref" style="inset-inline-start: ${pctNash}%" title="Nash puro: ${pctNash}%"></div>
          </div>
          <div class="mix-bar-foot">Nash base: ${fmtPct(pNash[idx], 1)} (${diffSigned})</div>
        </div>
      `;
    }).join("");

    mixEl.innerHTML = `
      <div class="mix-panel-head">
        <h3>Estrategia Mista Recalculada p*(theta) vs. Referencia Nash p*(0)</h3>
        <span class="mix-panel-sub">Barra verde: p*(${snap.theta.toFixed(2).replace(".", ",")}) | Marcador azul: p*(0) Nash</span>
      </div>
      <div class="mix-bars-grid">${barsHtml}</div>
    `;
  }

  function renderCoachHeatmap(scenario, snap) {
    const tbody = document.getElementById("coach-heatmap-body");
    const tfoot = document.getElementById("coach-heatmap-foot");
    if (!tbody || !tfoot) return;

    const flatVals = snap.ATheta.flat();
    const minVal = Math.min(...flatVals);
    const maxVal = Math.max(...flatVals);
    const span = Math.max(1e-4, maxVal - minVal);

    tbody.innerHTML = ZONES.map((gkZone, r) => {
      const cells = ZONES.map((shZone, c) => {
        const val = snap.ATheta[r][c];
        const baseVal = snap.A[r][c];
        const norm = (val - minVal) / span;
        const alpha = (0.04 + norm * 0.24).toFixed(3);
        const deltaPp = ((val - baseVal) * 100).toFixed(1);
        const deltaStr = `${Number(deltaPp) >= 0 ? "+" : ""}${deltaPp.replace(".", ",")} p.p.`;
        const misses = Number(scenario[`miss_${gkZone}_${shZone}`]);
        const nTotal = Number(scenario[`n_${gkZone}_${shZone}`]);
        return `
          <td class="heat-cell stat-cell" style="--heat-alpha: ${alpha}">
            <span class="heat-cell-main">${fmtPct(val, 2)} <span class="heat-delta">(${deltaStr})</span></span>
            <div class="heat-bar" aria-hidden="true"><span style="inline-size: ${(Math.min(1, val / 0.45) * 100).toFixed(1)}%"></span></div>
            <small>Base A: ${fmtPct(baseVal, 1)} | Obs: ${fmtInt(misses)}/${fmtInt(nTotal)}</small>
          </td>
        `;
      }).join("");

      return `
        <tr>
          <th scope="row">${escapeHtml(ZONE_LABELS[gkZone])} (p*=${fmtPct(snap.p[r], 1)})</th>
          ${cells}
        </tr>
      `;
    }).join("");

    const footCells = ZONES.map((shZone, j) => {
      const trueExp = snap.cornerTrue[j];
      const hybridExp = snap.cornerHybrid[j];
      const isWeakest = trueExp <= snap.vNash - 0.005;
      return `
        <td class="stat-cell">
          <div>Real vs ${shZone}: <strong>${fmtPct(trueExp, 2)}</strong></div>
          <small>Hibrido A(theta): ${fmtPct(hybridExp, 2)} | ${isWeakest ? "Exposto abaixo de Nash" : "Seguro vs Nash"}</small>
        </td>
      `;
    }).join("");

    tfoot.innerHTML = `
      <tr>
        <th scope="row">Taxa por Canto (p*(theta))</th>
        ${footCells}
      </tr>
    `;
  }

  function renderCoachSensitivitySvg(scenario, curveInfo, snap) {
    const svg = document.getElementById("coach-sensitivity-svg");
    const readout = document.getElementById("coach-chart-readout");
    if (!svg) return;

    const W = 680;
    const H = 310;
    const padL = 62;
    const padR = 24;
    const padT = 22;
    const padB = 46;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    const yMin = Math.max(0, Math.floor((curveInfo.minRate - 0.015) * 20) / 20);
    const yMax = Math.min(0.45, Math.ceil((curveInfo.maxRate + 0.02) * 20) / 20);
    const ySpan = Math.max(0.05, yMax - yMin);

    const xOf = (t) => (padL + t * plotW).toFixed(1);
    const yOf = (rate) => (padT + (1 - (rate - yMin) / ySpan) * plotH).toFixed(1);
    const poly = (picker) =>
      curveInfo.points.map((pt) => `${xOf(pt.theta)},${yOf(picker(pt))}`).join(" ");

    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((frac) => yMin + frac * ySpan);
    const yGridSvg = yTicks
      .map((val) => {
        const y = yOf(val);
        return `
          <line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="var(--border-subtle)" stroke-opacity="0.45" stroke-dasharray="3 4" />
          <text x="${padL - 8}" y="${y}" text-anchor="end" dominant-baseline="middle" fill="var(--ink-muted)" font-size="11">${(val * 100).toFixed(0)}%</text>
        `;
      })
      .join("");

    const xTicks = [0, 0.2, 0.4, 0.6, 0.8, 1];
    const xGridSvg = xTicks
      .map((val) => {
        const x = xOf(val);
        return `
          <line x1="${x}" y1="${padT}" x2="${x}" y2="${H - padB}" stroke="var(--border-subtle)" stroke-opacity="0.35" />
          <text x="${x}" y="${H - padB + 18}" text-anchor="middle" fill="var(--ink-muted)" font-size="11">${val.toFixed(1).replace(".", ",")}</text>
        `;
      })
      .join("");

    const critX = Number(xOf(curveInfo.criticalTheta));
    const curX = xOf(snap.theta);
    const curYV = yOf(snap.vStar);
    const curYE = yOf(snap.evVsEmp);
    const curYF = yOf(snap.worstFloor);

    svg.innerHTML = `
      <rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" rx="4" fill="var(--surface-card)" stroke="var(--border-subtle)" />
      <rect x="${critX}" y="${padT}" width="${Math.max(0, W - padR - critX).toFixed(1)}" height="${plotH}" fill="var(--risk-accent)" fill-opacity="0.08" />
      ${yGridSvg}
      ${xGridSvg}
      <line x1="${critX}" y1="${padT}" x2="${critX}" y2="${H - padB}" stroke="var(--risk-accent)" stroke-width="1.5" stroke-dasharray="5 4" />
      <polyline fill="none" stroke="var(--risk-accent)" stroke-width="2.5" stroke-linejoin="round" points="${poly((p) => p.worstFloor)}" />
      <polyline fill="none" stroke="var(--secondary-accent)" stroke-width="2.5" stroke-dasharray="6 3" stroke-linejoin="round" points="${poly((p) => p.evVsEmp)}" />
      <polyline fill="none" stroke="var(--accent)" stroke-width="3" stroke-linejoin="round" points="${poly((p) => p.vStar)}" />
      <line x1="${curX}" y1="${padT}" x2="${curX}" y2="${H - padB}" stroke="var(--ink-primary)" stroke-width="1.8" />
      <circle cx="${curX}" cy="${curYE}" r="5" fill="var(--secondary-accent)" stroke="var(--surface-card)" stroke-width="2" />
      <circle cx="${curX}" cy="${curYF}" r="5" fill="var(--risk-accent)" stroke="var(--surface-card)" stroke-width="2" />
      <circle cx="${curX}" cy="${curYV}" r="6" fill="var(--accent)" stroke="var(--surface-card)" stroke-width="2" />
      <text x="${Math.min(W - padR - 4, critX + 8)}" y="${padT + 16}" fill="var(--risk-accent)" font-size="11" font-weight="700" paint-order="stroke" stroke="var(--surface-card)" stroke-width="5" stroke-linejoin="round">theta_crit=${curveInfo.criticalTheta.toFixed(2).replace(".", ",")}</text>
      <text x="${padL + plotW / 2}" y="${H - 8}" text-anchor="middle" fill="var(--ink-secondary)" font-size="12" font-weight="600">Confianca no Scouting (theta)</text>
      <text x="16" y="${padT + plotH / 2}" text-anchor="middle" transform="rotate(-90 16 ${padT + plotH / 2})" fill="var(--ink-secondary)" font-size="12" font-weight="600">Taxa Nao-Gol (%)</text>
    `;

    if (readout) {
      readout.textContent = `Cenario ${scenario.scenario_code} em theta=${snap.theta.toFixed(2).replace(".", ",")}: V*(theta)=${fmtPct(snap.vStar, 2)} | Expectativa Empirica=${fmtPct(snap.evVsEmp, 2)} | Piso Pior Cenario=${fmtPct(snap.worstFloor, 2)}.`;
    }
  }

  function renderScenarioOverviewTable(scenarios, activeCode, curveCache, onPickScenario) {
    const tbody = document.getElementById("coach-overview-body");
    if (!tbody) return;

    tbody.innerHTML = scenarios
      .map((sc) => {
        const info = curveCache.get(sc.scenario_code);
        const critStr = info ? info.criticalTheta.toFixed(2).replace(".", ",") : "--";
        const { empReturns } = extractMatrixAndEmpirical(sc);
        const bestIdx = empReturns.indexOf(Math.max(...empReturns));
        const activeClass = sc.scenario_code === activeCode ? "overview-row-active" : "";
        return `
          <tr class="${activeClass}">
            <th scope="row">
              <button type="button" class="scenario-pick-btn" data-coach-pick="${escapeHtml(sc.scenario_code)}">
                ${escapeHtml(sc.scenario_label)}
              </button>
            </th>
            <td class="num">${fmtInt(sc.sample_size)}</td>
            <td class="num">${fmtPct(sc.game_value_v_primal, 2)}</td>
            <td class="num">${fmtPct(sc.gk_nash_L, 1)} L / ${fmtPct(sc.gk_nash_C, 1)} C / ${fmtPct(sc.gk_nash_R, 1)} R</td>
            <td class="num">${critStr}</td>
            <td class="num">${ZONES[bestIdx]} (${fmtPct(empReturns[bestIdx], 2)})</td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll("[data-coach-pick]").forEach((btn) => {
      btn.addEventListener("click", () => onPickScenario(btn.dataset.coachPick));
    });
  }

  function setupCoachSection(mart) {
    const scenarios = Array.isArray(mart.scenarios) ? mart.scenarios : [];
    const selectEl = document.getElementById("coach-scenario-select");
    const sliderEl = document.getElementById("coach-theta-slider");
    const outputEl = document.getElementById("coach-theta-output");
    const metaEl = document.getElementById("coach-scenario-meta");
    const breakLabelEl = document.getElementById("coach-theta-break-label");
    const critPresetBtn = document.getElementById("coach-preset-crit");
    const svgEl = document.getElementById("coach-sensitivity-svg");
    const presetBtns = Array.from(document.querySelectorAll(".theta-preset-btn"));
    if (!scenarios.length || !selectEl || !sliderEl) return;

    const curveCache = new Map();
    scenarios.forEach((sc) => curveCache.set(sc.scenario_code, buildScenarioCurveData(sc)));

    selectEl.innerHTML = scenarios
      .map(
        (sc) =>
          `<option value="${escapeHtml(sc.scenario_code)}">${escapeHtml(sc.scenario_label)}</option>`
      )
      .join("");

    function updateDashboard() {
      const scenario = scenarios.find((sc) => sc.scenario_code === selectEl.value) || scenarios[0];
      const curveInfo = curveCache.get(scenario.scenario_code);
      const theta = Number(sliderEl.value) || 0;
      const snap = evaluateCoachAtTheta(scenario, theta);
      const critFixed = curveInfo.criticalTheta.toFixed(2);
      const critComma = critFixed.replace(".", ",");

      syncSliderVars(sliderEl);
      if (metaEl) {
        metaEl.textContent = `n = ${fmtInt(scenario.sample_size)} cobrancas (${fmtInt(scenario.total_missed)} nao-gols) | Empirical Bayes alpha = ${Number(scenario.eb_alpha).toFixed(1).replace(".", ",")}`;
      }
      if (breakLabelEl) {
        breakLabelEl.textContent = `Ruptura ${critComma}`;
      }
      if (critPresetBtn) {
        critPresetBtn.dataset.theta = critFixed;
        critPresetBtn.textContent = `Ruptura (${critComma})`;
      }

      const thetaComma = theta.toFixed(2).replace(".", ",");
      const regimeDesc = snap.floorDrop <= 0.005 ? "Minimax Seguro" : "Exploracao de Scouting";
      if (outputEl) {
        outputEl.textContent = `${thetaComma} (${Math.round(theta * 100)}% | ${regimeDesc})`;
      }
      sliderEl.setAttribute(
        "aria-valuetext",
        `theta ${thetaComma}: V* ${fmtPct(snap.vStar, 2)}, piso ${fmtPct(snap.worstFloor, 2)}, ${regimeDesc}`
      );

      presetBtns.forEach((btn) => {
        const isMatch = Math.abs(Number(btn.dataset.theta) - theta) < 0.005;
        btn.setAttribute("aria-pressed", String(isMatch));
      });

      renderCoachKpis(scenario, snap, curveInfo);
      renderCoachMixPanel(scenario, snap);
      renderCoachHeatmap(scenario, snap);
      renderCoachSensitivitySvg(scenario, curveInfo, snap);
      renderScenarioOverviewTable(scenarios, scenario.scenario_code, curveCache, (pickedCode) => {
        selectEl.value = pickedCode;
        updateDashboard();
      });
    }

    selectEl.addEventListener("change", updateDashboard);
    sliderEl.addEventListener("input", updateDashboard);
    sliderEl.addEventListener("change", updateDashboard);

    presetBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        sliderEl.value = btn.dataset.theta || "0";
        updateDashboard();
      });
    });

    if (svgEl) {
      let dragging = false;
      const scrubFromPointer = (ev) => {
        const rect = svgEl.getBoundingClientRect();
        if (!rect.width) return;
        const vbX = ((ev.clientX - rect.left) / rect.width) * 680;
        const rawTheta = (vbX - 62) / (680 - 62 - 24);
        const clamped = Math.min(1, Math.max(0, rawTheta));
        sliderEl.value = clamped.toFixed(2);
        updateDashboard();
      };
      svgEl.addEventListener("pointerdown", (ev) => {
        dragging = true;
        if (svgEl.setPointerCapture) svgEl.setPointerCapture(ev.pointerId);
        scrubFromPointer(ev);
      });
      svgEl.addEventListener("pointermove", (ev) => {
        if (dragging) scrubFromPointer(ev);
      });
      svgEl.addEventListener("pointerup", () => {
        dragging = false;
      });
      svgEl.addEventListener("pointercancel", () => {
        dragging = false;
      });
    }

    updateDashboard();
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
