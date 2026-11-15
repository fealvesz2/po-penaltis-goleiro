/**
 * Portfolio Web Grupo 11 (UFABC Q3/2026) - Modulo Principal (Secoes 1 a 6)
 * Hidrata telemetria Gold de ./data/processed/po_penalties_mart.json,
 * renderiza equacoes KaTeX, executa Simplex 3x3 em tempo real (Treinador),
 * Dossies de Vestiario + Roleta de Nash (Goleiro) e Tradutor Analista -> Campo + Auditoria Excel.
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
    setupGloveSection(mart);
    setupBridgeSection(mart);
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

  function shooterToScenarioAdapter(shooter) {
    const out = {
      scenario_code: `SHOOTER_${shooter.scouting_rank}`,
      scenario_label: `${shooter.player} (${shooter.dominant_foot === "left-foot" ? "Canhoto" : "Destro"}, ${fmtInt(shooter.spatial_kicks)} espaciais)`,
      sample_size: shooter.spatial_kicks,
      eb_alpha: shooter.eb_alpha,
      total_missed: shooter.spatial_missed,
      gk_nash_L: shooter.gk_nash_L,
      gk_nash_C: shooter.gk_nash_C,
      gk_nash_R: shooter.gk_nash_R,
      shooter_emp_L: shooter.shot_pct_L,
      shooter_emp_C: shooter.shot_pct_C,
      shooter_emp_R: shooter.shot_pct_R,
      game_value_v_primal: shooter.game_value_v_nash,
      _shooter: shooter,
    };
    ZONES.forEach((gz) => {
      ZONES.forEach((sz) => {
        out[`a_${gz}_${sz}`] = shooter[`a_${gz}_${sz}`];
      });
    });
    return out;
  }

  function allocateIntegerShares(probs, totalUnits = 100) {
    const clean = probs.map((p) => Math.max(0, Number(p) || 0));
    const sum = clean.reduce((acc, v) => acc + v, 0) || 1;
    const scaled = clean.map((v, idx) => {
      const exact = (v / sum) * totalUnits;
      const base = Math.floor(exact);
      return { idx, base, rem: exact - base };
    });
    let remaining = totalUnits - scaled.reduce((acc, item) => acc + item.base, 0);
    const byRemainder = [...scaled].sort((a, b) => (b.rem !== a.rem ? b.rem - a.rem : a.idx - b.idx));
    for (let k = 0; k < remaining; k++) {
      byRemainder[k % byRemainder.length].base += 1;
    }
    return scaled.map((item) => item.base);
  }

  function buildRouletteBands(probs) {
    const plainLabels = {
      L: "Esquerda (E)",
      C: "Centro (C)",
      R: "Direita (D)",
    };
    const shares = allocateIntegerShares(probs, 100);
    let cursor = 0;
    return ZONES.map((zone, idx) => {
      const count = shares[idx];
      if (count <= 0) {
        return {
          zone,
          label: plainLabels[zone],
          pctInt: 0,
          prob: probs[idx],
          startTicket: null,
          endTicket: null,
          rangeText: "Nao sortear (0%)",
        };
      }
      const startTicket = cursor;
      const endTicket = cursor + count - 1;
      cursor += count;
      const pad = (n) => String(n).padStart(2, "0");
      return {
        zone,
        label: plainLabels[zone],
        pctInt: count,
        prob: probs[idx],
        startTicket,
        endTicket,
        rangeText: `${pad(startTicket)} a ${pad(endTicket)}`,
      };
    });
  }

  function drawUniformTicket() {
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      const buf = new Uint32Array(1);
      window.crypto.getRandomValues(buf);
      return Math.floor((buf[0] / 4294967296) * 100);
    }
    return Math.floor(Math.random() * 100);
  }

  function resolveTicketBand(bands, ticket) {
    return (
      bands.find(
        (b) => b.startTicket !== null && ticket >= b.startTicket && ticket <= b.endTicket
      ) || bands.reduce((best, cur) => (cur.pctInt > best.pctInt ? cur : best), bands[0])
    );
  }

  function formatPlayerSummaryPlain(shooter, snap) {
    const isLeft = shooter.dominant_foot === "left-foot";
    const footLabel = isLeft ? "Pe esquerdo" : "Pe direito";
    const topZone = ZONES[snap.p.indexOf(Math.max(...snap.p))];
    const topPct = Math.round(Math.max(...snap.p) * 100);
    const plainDir = { L: "Esquerda", C: "Meio", R: "Direita" };
    return {
      footLabel,
      topZone,
      topLabel: `${plainDir[topZone]} (${topPct}%)`,
    };
  }

  function buildGloveLockerTip(shooter, snap, modeTheta) {
    const plainDir = { L: "Esquerda", C: "Centro", R: "Direita" };
    const counts = [shooter.shot_count_L, shooter.shot_count_C, shooter.shot_count_R];
    const favIdx = ZONES.indexOf(shooter.favorite_shot_zone);
    const favCount = counts[favIdx];
    const favPct = Math.round((favCount / (shooter.spatial_kicks || 1)) * 100);
    const isLeft = shooter.dominant_foot === "left-foot";
    const cornerFlavor =
      shooter.favorite_tactical_corner === "Opposite"
        ? "canto aberto (cruzado)"
        : shooter.favorite_tactical_corner === "Natural"
          ? "canto natural (fechado)"
          : "faixa central";
    const centerZeroNote =
      shooter.shot_count_C === 0
        ? `Mesmo sem nenhum chute registrado no meio (${shooter.shot_count_C}/${shooter.spatial_kicks}), `
        : "";
    const topGkIdx = snap.p.indexOf(Math.max(...snap.p));

    if (modeTheta < 0.25) {
      return `<strong>Leitura de vestiario:</strong> ${escapeHtml(shooter.player)} (${isLeft ? "canhoto" : "destro"}) bateu ${favCount} de ${shooter.spatial_kicks} penaltis (${favPct}%) na ${plainDir[shooter.favorite_shot_zone]} (${cornerFlavor}). ${centerZeroNote}no plano blindado a maior cobertura vai para <strong>${plainDir[ZONES[topGkIdx]]} (${Math.round(snap.p[topGkIdx] * 100)}%)</strong> sem deixar o centro descoberto (${Math.round(snap.p[1] * 100)}%), impedindo que ele mude o canto ao perceber movimento precoce.`;
    }
    if (modeTheta < 0.75) {
      return `<strong>Ajuste equilibrado:</strong> Contra a tendencia historica de ${escapeHtml(shooter.player)} (${favPct}% em ${plainDir[shooter.favorite_shot_zone]}), o plano mistura a seguranca basica com a inclinacao de scouting. Se o batedor hesitar na passada, lembre que cair cedo demais para um unico lado derruba a protecao no pior cenario para <strong>${fmtPct(snap.worstFloor, 1)}</strong>.`;
    }
    return `<strong>Caca ao habito:</strong> Apostando totalmente no historico recente (${favCount}/${shooter.spatial_kicks} chutes em ${plainDir[shooter.favorite_shot_zone]}), a indicacao direta e saltar forte na <strong>${plainDir[ZONES[topGkIdx]]}</strong> (taxa esperada no habito dele: ${fmtPct(snap.evVsEmp, 1)}). Atencao: se o batedor trocar de lado nesta batida, a chance de defesa cai para <strong>${fmtPct(snap.worstFloor, 1)}</strong>.`;
  }

  function renderGloveGoalSvg(shooter, snap, activeZone) {
    const svg = document.getElementById("glove-goal-svg");
    const titleEl = document.getElementById("glove-goal-svg-title");
    if (!svg) return;

    const counts = [shooter.shot_count_L, shooter.shot_count_C, shooter.shot_count_R];
    const shotPcts = [shooter.shot_pct_L, shooter.shot_pct_C, shooter.shot_pct_R];
    const peakGkIdx = snap.p.indexOf(Math.max(...snap.p));
    const laneNames = ["Esquerda (L)", "Centro (C)", "Direita (R)"];
    const laneX = [36, 212, 388];
    const laneW = 176;

    const lanesMarkup = ZONES.map((zone, idx) => {
      const x = laneX[idx];
      const cx = x + laneW / 2;
      const gkProb = snap.p[idx];
      const shProb = shotPcts[idx];
      const barMaxH = 88;
      const gkH = Math.max(4, gkProb * barMaxH);
      const shH = Math.max(4, shProb * barMaxH);
      const isSpun = activeZone === zone;
      const isPeak = idx === peakGkIdx;
      const fillOpacity = (0.07 + gkProb * 0.34).toFixed(3);
      const borderStroke = isSpun
        ? "var(--focus-ring)"
        : isPeak
          ? "var(--accent)"
          : "var(--border-subtle)";
      const borderW = isSpun ? 3.5 : isPeak ? 2 : 1;

      return `
        <g>
          <rect
            x="${x + 4}"
            y="40"
            width="${laneW - 8}"
            height="164"
            rx="6"
            fill="rgba(var(--heat-rgb), ${fillOpacity})"
            stroke="${borderStroke}"
            stroke-width="${borderW}"
          />
          <text x="${cx}" y="62" text-anchor="middle" font-size="13" font-weight="700" fill="var(--ink-primary)">
            ${laneNames[idx]}
          </text>
          ${isSpun ? `<rect x="${cx - 50}" y="69" width="100" height="19" rx="9" fill="var(--focus-ring)" /><text x="${cx}" y="82" text-anchor="middle" font-size="10.5" font-weight="700" fill="#ffffff">ALVO SORTEADO</text>` : ""}
          <rect x="${cx - 48}" y="${182 - gkH}" width="38" height="${gkH.toFixed(1)}" rx="4" fill="var(--accent)" />
          <text x="${cx - 29}" y="${Math.max(98, 176 - gkH).toFixed(1)}" text-anchor="middle" font-size="11.5" font-weight="700" fill="var(--ink-primary)">
            ${Math.round(gkProb * 100)}%
          </text>
          <rect x="${cx + 10}" y="${182 - shH}" width="38" height="${shH.toFixed(1)}" rx="4" fill="var(--secondary-accent)" />
          <text x="${cx + 29}" y="${Math.max(98, 176 - shH).toFixed(1)}" text-anchor="middle" font-size="11.5" font-weight="700" fill="var(--ink-primary)">
            ${counts[idx]}/${shooter.spatial_kicks}
          </text>
          <text x="${cx - 29}" y="197" text-anchor="middle" font-size="10" font-weight="600" fill="var(--ink-secondary)">Plano GK</text>
          <text x="${cx + 29}" y="197" text-anchor="middle" font-size="10" font-weight="600" fill="var(--ink-secondary)">Chutes</text>
        </g>
      `;
    }).join("");

    svg.innerHTML = `
      <title id="glove-goal-svg-title">${escapeHtml(shooter.player)}: cobertura do goleiro (${Math.round(snap.p[0] * 100)}% esquerda, ${Math.round(snap.p[1] * 100)}% centro, ${Math.round(snap.p[2] * 100)}% direita) versus chutes do batedor.</title>
      <rect x="0" y="210" width="600" height="38" rx="6" fill="var(--accent-subtle)" />
      <line x1="20" y1="210" x2="580" y2="210" stroke="var(--accent)" stroke-width="2.5" />
      <path d="M 34 210 L 34 32 L 566 32 L 566 210" fill="none" stroke="var(--ink-primary)" stroke-width="5" stroke-linejoin="round" stroke-linecap="round" />
      <line x1="212" y1="36" x2="212" y2="206" stroke="var(--border-subtle)" stroke-dasharray="4 4" stroke-width="1" />
      <line x1="388" y1="36" x2="388" y2="206" stroke="var(--border-subtle)" stroke-dasharray="4 4" stroke-width="1" />
      ${lanesMarkup}
      <circle cx="154" cy="229" r="5" fill="var(--accent)" />
      <text x="165" y="233" font-size="11" font-weight="600" fill="var(--ink-primary)">Cobertura sugerida do goleiro</text>
      <circle cx="366" cy="229" r="5" fill="var(--secondary-accent)" />
      <text x="377" y="233" font-size="11" font-weight="600" fill="var(--ink-primary)">Chutes observados (${shooter.spatial_kicks})</text>
    `;
    if (titleEl) {
      titleEl.textContent = `${shooter.player}: baliza L/C/R`;
    }
  }

  function polarPoint(cx, cy, r, deg) {
    const rad = ((deg - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
  }

  function ringSectorPath(cx, cy, rOuter, rInner, startDeg, endDeg) {
    const largeArc = endDeg - startDeg > 180 ? 1 : 0;
    const [ox1, oy1] = polarPoint(cx, cy, rOuter, startDeg);
    const [ox2, oy2] = polarPoint(cx, cy, rOuter, endDeg);
    const [ix1, iy1] = polarPoint(cx, cy, rInner, endDeg);
    const [ix2, iy2] = polarPoint(cx, cy, rInner, startDeg);
    return [
      `M ${ox1.toFixed(2)} ${oy1.toFixed(2)}`,
      `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${ox2.toFixed(2)} ${oy2.toFixed(2)}`,
      `L ${ix1.toFixed(2)} ${iy1.toFixed(2)}`,
      `A ${rInner} ${rInner} 0 ${largeArc} 0 ${ix2.toFixed(2)} ${iy2.toFixed(2)}`,
      "Z",
    ].join(" ");
  }

  function renderGloveWheelSvg(bands, lastTicket, lastZone) {
    const svg = document.getElementById("glove-roulette-svg");
    if (!svg) return;
    const cx = 110;
    const cy = 110;
    const rOuter = 98;
    const rInner = 46;
    const zoneColors = {
      L: "var(--accent)",
      C: "var(--secondary-accent)",
      R: "var(--warning-accent)",
    };

    let cursorDeg = 0;
    const slicesMarkup = bands
      .map((band) => {
        if (band.pctInt <= 0) return "";
        const spanDeg = (band.pctInt / 100) * 360;
        const startDeg = cursorDeg;
        const endDeg = cursorDeg + spanDeg;
        cursorDeg = endDeg;
        const isActive = lastZone === band.zone;
        const opacity = isActive ? "0.95" : lastZone ? "0.42" : "0.78";
        if (band.pctInt >= 100) {
          return `<circle cx="${cx}" cy="${cy}" r="${(rOuter + rInner) / 2}" fill="none" stroke="${zoneColors[band.zone]}" stroke-width="${rOuter - rInner}" opacity="${opacity}" />`;
        }
        return `<path d="${ringSectorPath(cx, cy, rOuter, rInner, startDeg, endDeg)}" fill="${zoneColors[band.zone]}" opacity="${opacity}" stroke="var(--surface-card)" stroke-width="2" />`;
      })
      .join("");

    const needleDeg = lastTicket !== null ? ((lastTicket + 0.5) / 100) * 360 : 0;
    svg.style.setProperty("--needle-deg", `${needleDeg.toFixed(1)}deg`);

    svg.innerHTML = `
      ${slicesMarkup}
      <circle cx="${cx}" cy="${cy}" r="${rOuter}" fill="none" stroke="var(--border-control)" stroke-width="1.5" />
      <g class="roulette-needle">
        <line x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy - 86}" stroke="var(--ink-primary)" stroke-width="3.5" stroke-linecap="round" />
        <polygon points="${cx},${cy - 95} ${cx - 6},${cy - 80} ${cx + 6},${cy - 80}" fill="var(--focus-ring)" />
      </g>
    `;
  }

  function setupGloveSection(mart) {
    const allShooters = Array.isArray(mart.shooter_scouting) ? mart.shooter_scouting : [];
    const gridEl = document.getElementById("glove-shooter-grid");
    const filterStarsBtn = document.getElementById("glove-filter-stars");
    const filterAllBtn = document.getElementById("glove-filter-all");
    const modeBtns = Array.from(document.querySelectorAll(".glove-mode-btn"));
    const headerEl = document.getElementById("glove-card-header");
    const kpisEl = document.getElementById("glove-plain-kpis");
    const tipEl = document.getElementById("glove-locker-tip");
    const bandsEl = document.getElementById("glove-roulette-bands");
    const ticketEl = document.getElementById("glove-ticket-number");
    const resultEl = document.getElementById("glove-spin-result");
    const tallyEl = document.getElementById("glove-audit-tally");
    const spinBtn = document.getElementById("glove-spin-btn");
    const batchBtn = document.getElementById("glove-batch-btn");
    const resetBtn = document.getElementById("glove-reset-btn");

    if (!allShooters.length || !gridEl) return;

    const adapterMap = new Map();
    allShooters.forEach((s) => adapterMap.set(s.player, shooterToScenarioAdapter(s)));

    const state = {
      showAll: false,
      selectedPlayer: allShooters[0].player,
      modeTheta: 0,
      lastTicket: null,
      lastZone: null,
      spinCounts: { L: 0, C: 0, R: 0 },
      history: [],
    };

    function currentShooter() {
      return allShooters.find((s) => s.player === state.selectedPlayer) || allShooters[0];
    }

    function clearSpins(promptText) {
      state.lastTicket = null;
      state.lastZone = null;
      state.spinCounts = { L: 0, C: 0, R: 0 };
      state.history = [];
      if (ticketEl) ticketEl.textContent = "--";
      if (resultEl) {
        resultEl.classList.remove("is-spun");
        resultEl.innerHTML =
          promptText ||
          "Clique em <strong>Sortear Canto Agora</strong> para receber o comando do proximo penalti.";
      }
    }

    function renderChoiceCards() {
      const visibleList = state.showAll
        ? allShooters
        : allShooters.filter((s) => Boolean(s.is_featured_glove_star));
      if (!visibleList.some((s) => s.player === state.selectedPlayer) && visibleList.length) {
        state.selectedPlayer = visibleList[0].player;
      }

      gridEl.innerHTML = visibleList
        .map((s) => {
          const isChecked = s.player === state.selectedPlayer;
          const snap = evaluateCoachAtTheta(adapterMap.get(s.player), state.modeTheta);
          const plain = formatPlayerSummaryPlain(s, snap);
          return `
            <label class="glove-star-card">
              <input
                type="radio"
                name="glove_shooter"
                value="${escapeHtml(s.player)}"
                class="visually-hidden"
                ${isChecked ? "checked" : ""}
              >
              <div class="glove-star-top">
                <span class="glove-star-name">${escapeHtml(s.player)}</span>
                <span class="glove-star-check">${isChecked ? "Selecionado" : s.is_featured_glove_star ? "Estrela" : `#${s.scouting_rank}`}</span>
              </div>
              <span class="glove-star-meta">${escapeHtml(plain.footLabel)} | Carreira: ${fmtPct(s.career_conversion_rate, 1)} gol (${fmtInt(s.spatial_kicks)} espaciais)</span>
              <span class="glove-star-call">Principal: ${escapeHtml(plain.topLabel)}</span>
            </label>
          `;
        })
        .join("");

      gridEl.querySelectorAll('input[name="glove_shooter"]').forEach((radio) => {
        radio.addEventListener("change", () => {
          state.selectedPlayer = radio.value;
          clearSpins();
          renderChoiceCards();
          renderDossier();
        });
      });
    }

    function renderDossier() {
      const shooter = currentShooter();
      const snap = evaluateCoachAtTheta(adapterMap.get(shooter.player), state.modeTheta);
      const plain = formatPlayerSummaryPlain(shooter, snap);
      const bands = buildRouletteBands(snap.p);
      const favCornerPt =
        shooter.favorite_tactical_corner === "Opposite"
          ? "Canto cruzado"
          : shooter.favorite_tactical_corner === "Natural"
            ? "Canto natural"
            : "Meio";
      const favDirPt = { L: "Esquerda", C: "Centro", R: "Direita" }[shooter.favorite_shot_zone];
      const favShots =
        shooter.favorite_shot_zone === "L"
          ? shooter.shot_count_L
          : shooter.favorite_shot_zone === "C"
            ? shooter.shot_count_C
            : shooter.shot_count_R;
      const modeName =
        state.modeTheta < 0.25
          ? "Plano Blindado"
          : state.modeTheta < 0.75
            ? "Plano Equilibrado"
            : "Caca ao Habito";

      if (headerEl) {
        headerEl.innerHTML = `
          <div>
            <h3>${escapeHtml(shooter.player)}</h3>
            <p class="glove-card-sub">${escapeHtml(shooter.teams_list)} | ${escapeHtml(plain.footLabel)} | Carreira: ${fmtInt(shooter.career_total_kicks)} cobrancas (${fmtPct(shooter.career_conversion_rate, 1)} de conversao)</p>
          </div>
          <div class="glove-badges">
            <span class="pill">${escapeHtml(modeName)}</span>
            <span class="pill">Tendencia: ${escapeHtml(favCornerPt)}</span>
          </div>
        `;
      }

      if (kpisEl) {
        const guaranteedDefense = state.modeTheta < 0.25 ? snap.vStar : snap.worstFloor;
        const primaryLabel = state.modeTheta > 0.75 ? "Chance no habito historico" : "Defesa minima garantida";
        const primaryValue = state.modeTheta > 0.75 ? fmtPct(snap.evVsEmp, 1) : fmtPct(snap.vStar, 1);
        kpisEl.innerHTML = `
          <div class="mini-stat">
            <span>${primaryLabel}</span>
            <strong>${primaryValue}</strong>
            <small class="control-hint">Pior caso se ele mudar canto: ${fmtPct(guaranteedDefense, 1)}</small>
          </div>
          <div class="mini-stat">
            <span>Onde ele costuma bater</span>
            <strong>${escapeHtml(favDirPt)} (${favShots}/${shooter.spatial_kicks})</strong>
            <small class="control-hint">E: ${shooter.shot_count_L} | C: ${shooter.shot_count_C} | D: ${shooter.shot_count_R}</small>
          </div>
          <div class="mini-stat">
            <span>Foco principal da luva</span>
            <strong>${escapeHtml(plain.topLabel)}</strong>
            <small class="control-hint">E: ${Math.round(snap.p[0] * 100)}% | C: ${Math.round(snap.p[1] * 100)}% | D: ${Math.round(snap.p[2] * 100)}%</small>
          </div>
        `;
      }

      renderGloveGoalSvg(shooter, snap, state.lastZone);

      if (tipEl) {
        tipEl.innerHTML = buildGloveLockerTip(shooter, snap, state.modeTheta);
      }

      if (bandsEl) {
        bandsEl.innerHTML = bands
          .map((b) => {
            const cls = [
              "roulette-band-card",
              state.lastZone === b.zone ? "is-band-active" : "",
              b.pctInt === 0 ? "is-band-empty" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return `
              <div class="${cls}">
                <span>${escapeHtml(b.label)} (${b.pctInt}%)</span>
                <strong>${escapeHtml(b.rangeText)}</strong>
                <small>${b.pctInt > 0 ? `${b.pctInt} de 100 numeros` : "Faixa zerada neste modo"}</small>
              </div>
            `;
          })
          .join("");
      }

      renderGloveWheelSvg(bands, state.lastTicket, state.lastZone);

      if (tallyEl) {
        const totalSpins = state.spinCounts.L + state.spinCounts.C + state.spinCounts.R;
        if (totalSpins === 0) {
          tallyEl.innerHTML = `<span>Auditoria de sorteios: <strong>0</strong> realizados nesta sessao. Metas ativas: E ${bands[0].pctInt}% | C ${bands[1].pctInt}% | D ${bands[2].pctInt}%.</span>`;
        } else {
          const share = (k) => fmtPct(state.spinCounts[k] / totalSpins, 1);
          const recentPills = state.history
            .slice(0, 8)
            .map(
              (item) =>
                `<span class="tally-pill">#${String(item.ticket).padStart(2, "0")} ${item.zone === "L" ? "Esq" : item.zone === "C" ? "Cen" : "Dir"}</span>`
            )
            .join("");
          tallyEl.innerHTML = `
            <span>Total de sorteios: <strong>${totalSpins}</strong> | Esq: ${state.spinCounts.L} (${share("L")} vs ${bands[0].pctInt}%) | Cen: ${state.spinCounts.C} (${share("C")} vs ${bands[1].pctInt}%) | Dir: ${state.spinCounts.R} (${share("R")} vs ${bands[2].pctInt}%)</span>
            <div class="tally-pills" aria-label="Ultimos numeros sorteados">${recentPills}</div>
          `;
        }
      }
    }

    function executeSpinBatch(count = 1) {
      const shooter = currentShooter();
      const snap = evaluateCoachAtTheta(adapterMap.get(shooter.player), state.modeTheta);
      const bands = buildRouletteBands(snap.p);
      let lastDrawn = null;
      let lastBand = null;

      for (let i = 0; i < count; i++) {
        const t = drawUniformTicket();
        const b = resolveTicketBand(bands, t);
        state.spinCounts[b.zone] += 1;
        state.history.unshift({ ticket: t, zone: b.zone });
        lastDrawn = t;
        lastBand = b;
      }
      if (state.history.length > 40) state.history.length = 40;

      state.lastTicket = lastDrawn;
      state.lastZone = lastBand.zone;
      const padded = String(lastDrawn).padStart(2, "0");
      if (ticketEl) ticketEl.textContent = padded;
      if (resultEl) {
        resultEl.classList.add("is-spun");
        const dirOrder = {
          L: "SALTAR PARA A ESQUERDA (LADO DO BATEDOR)",
          C: "SEGURAR NO CENTRO DA BALIZA",
          R: "SALTAR PARA A DIREITA (LADO DO BATEDOR)",
        }[lastBand.zone];
        const prefix = count > 1 ? `Lote de ${count} sorteios concluido. Ultimo sinal ` : "Sinal sorteado ";
        resultEl.innerHTML = `${prefix}<strong>#${padded}</strong> (faixa ${escapeHtml(lastBand.rangeText)}): <strong>${dirOrder}</strong> contra ${escapeHtml(shooter.player)}.`;
      }
      renderDossier();
    }

    if (filterStarsBtn && filterAllBtn) {
      const syncFilter = (showAll) => {
        state.showAll = showAll;
        filterStarsBtn.setAttribute("aria-pressed", String(!showAll));
        filterAllBtn.setAttribute("aria-pressed", String(showAll));
        clearSpins();
        renderChoiceCards();
        renderDossier();
      };
      filterStarsBtn.addEventListener("click", () => syncFilter(false));
      filterAllBtn.addEventListener("click", () => syncFilter(true));
    }

    modeBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modeTheta = Number(btn.dataset.gloveTheta) || 0;
        modeBtns.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        clearSpins("Modo de plano atualizado. Clique em <strong>Sortear Canto Agora</strong> para testar as novas faixas.");
        renderChoiceCards();
        renderDossier();
      });
    });

    if (spinBtn) spinBtn.addEventListener("click", () => executeSpinBatch(1));
    if (batchBtn) batchBtn.addEventListener("click", () => executeSpinBatch(10));
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        clearSpins();
        renderDossier();
      });
    }

    renderChoiceCards();
    renderDossier();
  }

  function setupBridgeSection(mart) {
    const scenarios = Array.isArray(mart.scenarios) ? mart.scenarios : [];
    const shooters = Array.isArray(mart.shooter_scouting) ? mart.shooter_scouting : [];
    const selectEl = document.getElementById("bridge-target-select");
    const sliderEl = document.getElementById("bridge-theta-slider");
    const outputEl = document.getElementById("bridge-theta-output");
    const metaEl = document.getElementById("bridge-target-meta");
    const breakLabelEl = document.getElementById("bridge-theta-break-label");
    const critPresetBtn = document.getElementById("bridge-preset-crit");
    const summaryEl = document.getElementById("bridge-live-summary");
    const stepsEl = document.getElementById("bridge-steps-grid");
    const presetBtns = Array.from(document.querySelectorAll(".bridge-preset-btn"));

    if (!scenarios.length || !selectEl || !sliderEl) return;

    const targetMap = new Map();
    const curveCache = new Map();

    const scenarioOptions = scenarios
      .map((sc) => {
        const key = `scenario:${sc.scenario_code}`;
        targetMap.set(key, { kind: "scenario", record: sc, shooter: null });
        curveCache.set(key, buildScenarioCurveData(sc));
        return `<option value="${escapeHtml(key)}">${escapeHtml(sc.scenario_label)}</option>`;
      })
      .join("");

    const shooterOptions = shooters
      .map((sh) => {
        const key = `shooter:${sh.player}`;
        const adapted = shooterToScenarioAdapter(sh);
        targetMap.set(key, { kind: "shooter", record: adapted, shooter: sh });
        curveCache.set(key, buildScenarioCurveData(adapted));
        return `<option value="${escapeHtml(key)}">${escapeHtml(sh.player)} (${sh.dominant_foot === "left-foot" ? "Canhoto" : "Destro"}, ${sh.spatial_kicks} espaciais)</option>`;
      })
      .join("");

    selectEl.innerHTML = `
      <optgroup label="Cenarios Taticos Coletivos (6)">${scenarioOptions}</optgroup>
      <optgroup label="Batedores Individuais - Empirical Bayes alpha=5,0 (10)">${shooterOptions}</optgroup>
    `;

    function renderBridgeTranslation() {
      const targetKey = selectEl.value;
      const entry = targetMap.get(targetKey) || Array.from(targetMap.values())[0];
      const rec = entry.record;
      const curveInfo = curveCache.get(targetKey);
      const theta = Number(sliderEl.value) || 0;
      const snap = evaluateCoachAtTheta(rec, theta);
      const critFixed = curveInfo.criticalTheta.toFixed(2);
      const critComma = critFixed.replace(".", ",");
      const thetaComma = theta.toFixed(2).replace(".", ",");

      syncSliderVars(sliderEl);
      if (metaEl) {
        metaEl.textContent =
          entry.kind === "scenario"
            ? `Cenario BigQuery Gold | n = ${fmtInt(rec.sample_size)} cobrancas | alpha EB = ${Number(rec.eb_alpha).toFixed(1).replace(".", ",")}`
            : `Dossie individual | Clube(s): ${entry.shooter.teams_list} | n = ${fmtInt(rec.sample_size)} espaciais (alpha = 5,0)`;
      }
      if (breakLabelEl) breakLabelEl.textContent = `Corte ${critComma}`;
      if (critPresetBtn) {
        critPresetBtn.dataset.bridgeTheta = critFixed;
        critPresetBtn.textContent = `Corte (${critComma})`;
      }

      const isSafe = snap.floorDrop <= 0.005;
      const regimeBadge = isSafe ? "Blindado (Minimax)" : "Inclinado (Com Risco)";
      if (outputEl) {
        outputEl.textContent = `${thetaComma} (${Math.round(theta * 100)}% | ${regimeBadge})`;
      }
      sliderEl.setAttribute(
        "aria-valuetext",
        `theta ${thetaComma}, V* ${fmtPct(snap.vStar, 2)}, piso ${fmtPct(snap.worstFloor, 2)}`
      );

      presetBtns.forEach((btn) => {
        const isMatch = Math.abs(Number(btn.dataset.bridgeTheta) - theta) < 0.005;
        btn.setAttribute("aria-pressed", String(isMatch));
      });

      const kicks10 = allocateIntegerShares(snap.p, 10);
      const bands100 = buildRouletteBands(snap.p);
      const activeDualZones = snap.qTilde
        .map((qVal, idx) => (qVal > 0.01 ? `${ZONES[idx]} (${fmtPct(qVal, 1)})` : null))
        .filter(Boolean)
        .join(", ");
      const exposedIdx = snap.cornerTrue.indexOf(Math.min(...snap.cornerTrue));
      const exposedCornerPt = { L: "Esquerda", C: "Centro", R: "Direita" }[ZONES[exposedIdx]];
      const diagRates = [snap.A[0][0], snap.A[1][1], snap.A[2][2]];
      const bestTrainIdx = snap.p[1] >= 0.35 ? 1 : snap.p.indexOf(Math.max(...snap.p));
      const trainFocus =
        bestTrainIdx === 1
          ? `Segurar o tempo de salto no Centro (${Math.round(snap.p[1] * 100)}% do plano, diag. ${fmtPct(diagRates[1], 1)}) para nao entregar chute facil no meio.`
          : `Priorizar impulsao explosiva para ${ZONES[bestTrainIdx] === "L" ? "Esquerda" : "Direita"} (${kicks10[bestTrainIdx]} de cada 10 repeticoes, taxa no acerto ${fmtPct(diagRates[bestTrainIdx], 1)}).`;

      if (summaryEl) {
        summaryEl.textContent = `Resumo da Traducao (${rec.scenario_code}): em theta = ${thetaComma}, o goleiro executa ${kicks10[0]}E / ${kicks10[1]}C / ${kicks10[2]}D a cada 10 cobrancas, mantendo piso ${fmtPct(snap.worstFloor, 2)} (regime ${regimeBadge}).`;
      }

      if (stepsEl) {
        const upliftPp = (snap.upliftVsNash * 100).toFixed(2).replace(".", ",");
        const dropPp = (snap.floorDrop * 100).toFixed(2).replace(".", ",");
        const stepsData = [
          {
            title: "Passo 1 | Restricao Primal-Dual -> Regra de Seguranca do Goleiro",
            analyst: `Restricoes \\(\\sum_i p_i a_{ij}(\\theta) \\ge\\) <strong>${fmtPct(snap.vStar, 2)}</strong> ativas com suporte dual \\(\\tilde{q} =\\) <code>[${escapeHtml(activeDualZones)}]</code>. Piso sem exploracao: <strong>${fmtPct(snap.worstFloor, 2)}</strong> vs. expectativa no scouting <strong>${fmtPct(snap.evVsEmp, 2)}</strong>.`,
            field: isSafe
              ? `<strong>Ordem de vestiario:</strong> "Nenhuma brecha aberta. Mesmo que o batedor mude o canto de ultima hora, seu piso defensivo continua travado em ${fmtPct(snap.worstFloor, 2)}."`
              : `<strong>Alerta tatico:</strong> "Voce ganha expectativa contra o habito, mas o canto <strong>${exposedCornerPt}</strong> fica exposto (cai ${dropPp} p.p. para ${fmtPct(snap.worstFloor, 2)} se o adversario perceber a leitura)."`,
          },
          {
            title: "Passo 2 | Probabilidades p* -> Repertorio de 10 e Faixas 00-99",
            analyst: `Vetor otimo continuo \\(p^*(\\theta) =\\) <code>(${fmtPct(snap.p[0], 1)} L, ${fmtPct(snap.p[1], 1)} C, ${fmtPct(snap.p[2], 1)} R)</code> com \\(\\sum p_i = 1\\).`,
            field: `<strong>Sinal na garrafa:</strong> "Em 10 batidas: <strong>${kicks10[0]} Esquerda, ${kicks10[1]} Centro, ${kicks10[2]} Direita</strong>." Cartao numerico (00-99): E <code>${bands100[0].rangeText}</code> | C <code>${bands100[1].rangeText}</code> | D <code>${bands100[2].rangeText}</code>.`,
          },
          {
            title: "Passo 3 | Fronteira Critica theta_crit -> Gatilho Pre-Jogo",
            analyst: `Parametro atual \\(\\theta = ${thetaComma}\\) comparado ao corte \\(\\theta_{\\text{crit}} = ${critComma}\\). Ganho garantido sobre Nash puro: <strong>+${upliftPp} p.p.</strong>`,
            field:
              theta < curveInfo.criticalTheta
                ? `<strong>Decisao pre-jogo:</strong> "Confianca ainda abaixo de ${critComma}. Nao compensa abandonar a roleta equilibrada: o pequeno ganho esperado nao paga a perda de piso."`
                : `<strong>Decisao pre-jogo:</strong> "Confianca acima do corte ${critComma}. Dossie autorizado para inclinar os saltos para a <strong>${{ L: "Esquerda", C: "Centro", R: "Direita" }[snap.bestEmpCorner]}</strong>."`,
          },
          {
            title: "Passo 4 | Matriz A e Taxa Central -> Rotina de Treino Semanal",
            analyst: `Diagonais de acerto observadas/regularizadas: L = ${fmtPct(diagRates[0], 1)}, C = ${fmtPct(diagRates[1], 1)}, R = ${fmtPct(diagRates[2], 1)}; erro central sem centro coberto: L-C = ${fmtPct(snap.A[0][1], 1)}, R-C = ${fmtPct(snap.A[2][1], 1)}.`,
            field: `<strong>Protocolo no CT:</strong> ${trainFocus}`,
          },
        ];

        stepsEl.innerHTML = stepsData
          .map(
            (st) => `
            <article class="bridge-step-card">
              <h3 class="bridge-step-title">${st.title}</h3>
              <div class="bridge-lens-pair">
                <div class="bridge-lens-box bridge-lens-analyst">
                  <span class="bridge-lens-kicker">Analista (Simplex LP)</span>
                  <p>${st.analyst}</p>
                </div>
                <div class="bridge-arrow" aria-hidden="true">&rarr;</div>
                <div class="bridge-lens-box bridge-lens-field">
                  <span class="bridge-lens-kicker">Campo / Goleiro (Zero Jargao)</span>
                  <p>${st.field}</p>
                </div>
              </div>
            </article>
          `
          )
          .join("");
        renderMath(stepsEl);
      }
    }

    selectEl.addEventListener("change", renderBridgeTranslation);
    sliderEl.addEventListener("input", renderBridgeTranslation);
    sliderEl.addEventListener("change", renderBridgeTranslation);
    presetBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        sliderEl.value = btn.dataset.bridgeTheta || "0";
        renderBridgeTranslation();
      });
    });

    renderBridgeTranslation();
    renderBridgeReconcileTable(mart);
  }

  function renderBridgeReconcileTable(mart) {
    const tbody = document.getElementById("bridge-reconcile-body");
    if (!tbody) return;
    const scenarios = Array.isArray(mart.scenarios) ? mart.scenarios : [];
    const curves = Array.isArray(mart.sensitivity_curves) ? mart.sensitivity_curves : [];

    tbody.innerHTML = scenarios
      .map((sc) => {
        const checkpoints = [0.0, 0.5, 1.0].map((thetaVal) => {
          const goldPt = curves.find(
            (pt) =>
              pt.scenario_code === sc.scenario_code && Math.abs(Number(pt.theta) - thetaVal) < 1e-4
          );
          const jsSnap = evaluateCoachAtTheta(sc, thetaVal);
          const goldV = goldPt ? Number(goldPt.game_value_v_primal) : Number(sc.game_value_v_primal);
          const diff = Math.abs(jsSnap.vStar - goldV);
          return { goldV, jsV: jsSnap.vStar, diff };
        });
        const maxDiff = Math.max(...checkpoints.map((c) => c.diff));
        const ok = maxDiff < 1e-5;
        return `
          <tr>
            <th scope="row"><code>${escapeHtml(sc.scenario_code)}</code></th>
            <td class="num">${fmtPct(checkpoints[0].goldV, 2)} / ${fmtPct(checkpoints[0].jsV, 2)}</td>
            <td class="num">${fmtPct(checkpoints[1].goldV, 2)} / ${fmtPct(checkpoints[1].jsV, 2)}</td>
            <td class="num">${fmtPct(checkpoints[2].goldV, 2)} / ${fmtPct(checkpoints[2].jsV, 2)}</td>
            <td class="num"><code>${maxDiff.toExponential(2)}</code></td>
            <td><span class="regime-pill ${ok ? "regime-pill-safe" : "regime-pill-alert"}">${ok ? "Conciliado" : "Divergente"}</span></td>
          </tr>
        `;
      })
      .join("");
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
